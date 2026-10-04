"""/debug/trace developer page. Sources are faked; the run itself needs PostgreSQL."""

from datetime import UTC, datetime

import httpx
import pytest

from app.main import app
from app.routes import debug
from app.services import news_ingestion as ni


@pytest.fixture
def fake_sources(monkeypatch):
    async def gdelt(keywords, timespan, client):
        return [{"title": "RBI holds repo rate", "url": "https://example.com/rbi", "seendate": datetime(2026, 10, 4, tzinfo=UTC),
                 "domain": "example.com", "sourcecountry": "India"}]

    async def google(keyword, client):
        ni.logger.error("[google_rss] HTTP 503: Service Unavailable")  # simulate a logged failure
        return []

    async def marketaux(symbol, client):
        raise AssertionError("not a ticker: Marketaux must not be called")

    monkeypatch.setattr(ni, "fetch_gdelt_many", gdelt)
    monkeypatch.setattr(ni, "fetch_google_news_rss", google)
    monkeypatch.setattr(ni, "fetch_marketaux", marketaux)


async def test_page_is_served(client):
    r = await client.get("/debug/trace")
    assert r.status_code == 200 and "<form" in r.text and "/debug/trace/run" in r.text


async def test_trace_shows_raw_articles_rows_and_errors(pg_client, pg_sessionmaker, fake_sources):
    app.dependency_overrides[debug.get_session_factory] = lambda: pg_sessionmaker
    r = await pg_client.post("/debug/trace/run", params={"keyword": "RBI repo rate", "timespan": "1d"})
    text = r.text

    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "no ticker (Marketaux skipped)" in text
    # step 1: raw article with its fields
    assert "[gdelt] ['RBI repo rate'] -> 1 article(s)" in text
    assert "RBI holds repo rate" in text and "sourcecountry: India" in text
    assert "[google_rss] 'RBI repo rate' -> 0 article(s)" in text
    # step 2: the row that was written, unscanned
    assert "inserted 1 new row(s)" in text
    assert "[gdelt] security_status=safe" in text
    assert "security_reason: no injection patterns matched" in text
    # step 3: the logged error
    assert "ERROR app.services.news_ingestion: [google_rss] HTTP 503" in text


async def test_trace_reports_database_failure(client, fake_sources):
    class Broken:
        def __call__(self):
            raise ConnectionRefusedError("database down")

    app.dependency_overrides[debug.get_session_factory] = lambda: Broken()
    r = await client.post("/debug/trace/run", params={"keyword": "war"})
    assert r.status_code == 200
    assert "INGESTION FAILED: ConnectionRefusedError: database down" in r.text
    assert "nothing (ingestion failed" in r.text


async def test_rejects_requests_from_other_machines():
    transport = httpx.ASGITransport(app=app, client=("192.168.1.50", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as remote:
        assert (await remote.get("/debug/trace")).status_code == 403
        assert (await remote.post("/debug/trace/run", params={"keyword": "war"})).status_code == 403


async def test_input_validation(client):
    assert (await client.post("/debug/trace/run", params={"keyword": ""})).status_code == 422
    assert (await client.post("/debug/trace/run", params={"keyword": "war", "timespan": "drop table"})).status_code == 422
