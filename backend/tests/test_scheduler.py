"""
Scheduler tests: watchlist query, job bookkeeping/logging, start/stop.
The real ingestion / market functions are replaced with fakes, so no network
is used. Runs on in-memory SQLite.
"""

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core import scheduler
from app.core.config import settings
from app.models import PortfolioHolding, User
from app.models.enums import AssetType, TransactionSource
from app.services import fundamentals, market_data, news_ingestion
from tests.conftest import signup_headers


@pytest.fixture(autouse=True)
def clean_scheduler_state(monkeypatch):
    monkeypatch.setattr(scheduler, "_last_runs", {})
    monkeypatch.setattr(scheduler, "_running_tasks", set())
    monkeypatch.setattr(settings, "SCHEDULER_ENABLED", True)
    monkeypatch.setattr(settings, "SCHEDULER_FIRST_RUN_DELAY_SECONDS", 3600)  # never fire during a test


async def seed_holdings(session_factory) -> None:
    def holding(user_id, asset_type, symbol, source=TransactionSource.MANUAL):
        return PortfolioHolding(user_id=user_id, asset_type=asset_type, symbol=symbol, quantity=Decimal(1),
                                avg_buy_price=Decimal(100), source=source)

    async with session_factory() as db:
        db.add_all([User(id=1, email="a@x.com", hashed_password="x"), User(id=2, email="b@x.com", hashed_password="x")])
        await db.flush()
        db.add_all([
            holding(1, AssetType.STOCK, "TCS.NS"),
            holding(1, AssetType.STOCK, "RELIANCE.NS"),
            holding(1, AssetType.FD, "SBI FD 2027"),                                   # not a stock
            holding(2, AssetType.STOCK, "RELIANCE.NS"),                                # held twice
            holding(2, AssetType.STOCK, "TCS.NS", TransactionSource.KITE_SYNC),        # synced copy
            holding(2, AssetType.GOLD, "Gold coins"),
        ])
        await db.commit()


# ---------------- watchlist ----------------

async def test_held_stock_symbols_are_distinct_stocks_only(db_sessionmaker):
    await seed_holdings(db_sessionmaker)
    assert await scheduler.held_stock_symbols(db_sessionmaker) == ["RELIANCE.NS", "TCS.NS"]


async def test_news_watchlist_is_macro_keywords_plus_holdings(db_sessionmaker):
    await seed_holdings(db_sessionmaker)
    assert await scheduler.build_news_watchlist(db_sessionmaker) == [
        "war", "recession", "RBI repo rate", "crude oil", "RELIANCE.NS", "TCS.NS",
    ]


async def test_news_watchlist_with_no_holdings(db_sessionmaker):
    assert await scheduler.build_news_watchlist(db_sessionmaker) == scheduler.MACRO_SHOCK_KEYWORDS


# ---------------- jobs ----------------

async def test_news_job_runs_ingestion_and_records_summary(db_sessionmaker, monkeypatch, caplog):
    await seed_holdings(db_sessionmaker)
    seen = {}

    async def fake_ingest(keywords, session_factory):
        seen["keywords"] = keywords
        return news_ingestion.IngestionReport(fetched={"gdelt": 0, "google_rss": 40, "marketaux": 2}, inserted=30, duplicates=12)

    monkeypatch.setattr(news_ingestion, "ingest_news_for_watchlist", fake_ingest)
    job = scheduler._logged_job("news_test", lambda record: scheduler.news_job_body(record, db_sessionmaker))
    caplog.set_level("INFO", logger="app.scheduler")
    await job()

    run = scheduler._last_runs["news_test"]
    assert seen["keywords"][-2:] == ["RELIANCE.NS", "TCS.NS"]
    assert run.status == "ok" and run.items == 6 and run.details["inserted"] == 30
    assert run.finished_at is not None and run.duration_s is not None
    assert "[news_test] run started" in caplog.text and "status=ok items=6" in caplog.text


async def test_news_job_sends_new_articles_through_embedding(db_sessionmaker, monkeypatch):
    from app.services import vector_store

    async def fake_ingest(keywords, session_factory):
        return news_ingestion.IngestionReport(fetched={"gdelt": 0, "google_rss": 3, "marketaux": 0},
                                              inserted=3, inserted_ids=[11, 12, 13])

    seen = {}

    async def fake_embed_many(ids, session_factory):
        seen["ids"] = ids
        return vector_store.EmbedReport(embedded=[11, 12], quarantined=[13])

    monkeypatch.setattr(news_ingestion, "ingest_news_for_watchlist", fake_ingest)
    monkeypatch.setattr(vector_store, "embed_many", fake_embed_many)
    await scheduler._logged_job("news_test", lambda r: scheduler.news_job_body(r, db_sessionmaker))()

    run = scheduler._last_runs["news_test"]
    assert seen["ids"] == [11, 12, 13]
    assert run.details["embedded"] == 2 and run.details["quarantined"] == 1 and run.status == "ok"


async def test_news_job_survives_embedding_failure(db_sessionmaker, monkeypatch):
    from app.services import vector_store

    async def fake_ingest(keywords, session_factory):
        return news_ingestion.IngestionReport(fetched={"gdelt": 1, "google_rss": 0, "marketaux": 0},
                                              inserted=1, inserted_ids=[5])

    async def broken_embed(ids, session_factory):
        raise OSError("model download failed")

    monkeypatch.setattr(news_ingestion, "ingest_news_for_watchlist", fake_ingest)
    monkeypatch.setattr(vector_store, "embed_many", broken_embed)
    await scheduler._logged_job("news_test", lambda r: scheduler.news_job_body(r, db_sessionmaker))()

    run = scheduler._last_runs["news_test"]
    assert run.status == "partial" and "embedding step failed: OSError" in run.errors[0]


async def test_news_job_flags_when_nothing_was_fetched(db_sessionmaker, monkeypatch):
    async def fake_ingest(keywords, session_factory):
        return news_ingestion.IngestionReport()

    monkeypatch.setattr(news_ingestion, "ingest_news_for_watchlist", fake_ingest)
    await scheduler._logged_job("news_test", lambda r: scheduler.news_job_body(r, db_sessionmaker))()
    assert scheduler._last_runs["news_test"].status == "partial"
    assert "no articles fetched" in scheduler._last_runs["news_test"].errors[0]


async def test_market_job_counts_successes_and_errors(db_sessionmaker, monkeypatch):
    await seed_holdings(db_sessionmaker)
    db_sessionmaker_symbols = []

    async def fake_update(symbol, session_factory):
        db_sessionmaker_symbols.append(symbol)
        if symbol == "TCS.NS":
            raise RuntimeError("boom")
        return market_data.MarketUpdate(symbol, SimpleNamespace(source="yfinance"), None, 1)

    async def fake_fundamentals(symbol, session_factory):
        return object() if symbol == "RELIANCE.NS" else None

    monkeypatch.setattr(market_data, "update_market_snapshot", fake_update)
    monkeypatch.setattr(fundamentals, "refresh_if_stale", fake_fundamentals)
    await scheduler._logged_job("market_test", lambda r: scheduler.market_job_body(r, db_sessionmaker))()

    run = scheduler._last_runs["market_test"]
    assert db_sessionmaker_symbols == ["RELIANCE.NS", "TCS.NS"]  # one failure didn't stop the loop
    assert (run.items, run.succeeded, run.status) == (2, 1, "partial")
    assert run.errors == ["TCS.NS: RuntimeError: boom"]
    assert run.details["price_sources"] == {"yfinance": 1} and run.details["with_fundamentals"] == 1


async def test_job_crash_is_logged_not_raised():
    async def broken(record):
        raise ConnectionRefusedError("database down")

    await scheduler._logged_job("broken", broken)()  # must not raise
    run = scheduler._last_runs["broken"]
    assert run.status == "failed" and "database down" in run.errors[0]


# ---------------- lifecycle ----------------

async def test_start_registers_both_jobs_and_stop_shuts_down():
    scheduler.start_scheduler()
    try:
        status = scheduler.get_status()
        assert status["running"] is True
        jobs = {job["id"]: job for job in status["jobs"]}
        assert set(jobs) == {"news_ingestion", "market_update"}
        assert scheduler._scheduler.get_job("news_ingestion").trigger.interval.total_seconds() == 600
        assert scheduler._scheduler.get_job("market_update").trigger.interval.total_seconds() == 1800
    finally:
        await scheduler.stop_scheduler()
    assert scheduler.get_status()["running"] is False


async def test_disabled_scheduler_does_not_start(monkeypatch):
    monkeypatch.setattr(settings, "SCHEDULER_ENABLED", False)
    scheduler.start_scheduler()
    assert scheduler.get_status()["running"] is False


async def test_stop_cancels_a_run_in_progress():
    started = asyncio.Event()

    async def slow(record):
        started.set()
        await asyncio.sleep(3600)

    task = asyncio.create_task(scheduler._logged_job("slow", slow)())
    await started.wait()
    await scheduler.stop_scheduler()
    assert task.cancelled()
    assert scheduler._last_runs["slow"].errors == ["cancelled (app shutting down)"]


# ---------------- status endpoint ----------------

async def test_scheduler_status_endpoint_requires_login(client):
    assert (await client.get("/health/scheduler")).status_code == 401
    headers = await signup_headers(client)
    body = (await client.get("/health/scheduler", headers=headers)).json()
    assert body == {"running": False, "jobs": [], "last_runs": {}}
