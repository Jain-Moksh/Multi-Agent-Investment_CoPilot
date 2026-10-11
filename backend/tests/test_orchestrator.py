"""
LangGraph orchestrator: fan-out/fan-in, real parallelism, failure isolation, and an
end-to-end run with the five REAL agents on PostgreSQL (TEST_DATABASE_URL).
"""

import asyncio
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.agents import orchestrator as orch
from app.agents.orchestrator import AGENT_NAMES, UnknownSymbolError, UnknownUserError, build_graph, run_analysis
from app.models import AgentLog, CompanyFundamentals, MarketSnapshot, PortfolioHolding, PriceHistory, User
from app.models.enums import AssetType, TransactionSource
from app.services import fundamentals, llm, market_data
from tests.test_vector_store import chroma, fake_model  # noqa: F401  (fixtures)

AGENT_CLASSES = {"news_agent": "NewsAgent", "market_agent": "MarketAgent", "portfolio_agent": "PortfolioAgent",
                 "user_profiling_agent": "UserProfilingAgent",
                 "fundamental_economic_agent": "FundamentalEconomicAgent"}


def fake_agent_class(name: str, delay: float = 0.5, fail: Exception | None = None, calls: list | None = None):
    class FakeAgent:
        def __init__(self, session_factory):
            self.session_factory = session_factory

        async def analyze(self, *args, **kwargs):
            if calls is not None:
                calls.append((name, args, kwargs))
            await asyncio.sleep(delay)
            if fail:
                raise fail
            return {"agent": name, "status": "ok", "signal": 0.5, "confidence": 0.8, "summary": f"{name} done"}

    return FakeAgent


@pytest.fixture
def user(pg_sessionmaker):
    async def make(user_id=1):
        async with pg_sessionmaker() as db:
            db.add(User(id=user_id, email=f"u{user_id}@x.com", hashed_password="x"))
            await db.commit()
    return make


@pytest.fixture
def fakes(monkeypatch):
    """Replace all five agents with fakes; returns a function to customise individual ones."""
    calls: list = []

    def install(**overrides):
        for name, cls_name in AGENT_CLASSES.items():
            monkeypatch.setattr(orch, cls_name, overrides.get(name) or fake_agent_class(name, calls=calls))
    install()

    async def no_fundamentals(symbol, session_factory):
        return type("Row", (), {"name": "Infosys Limited"})()

    monkeypatch.setattr(fundamentals, "refresh_if_stale", no_fundamentals)

    # No network: pretend the on-demand price fetch worked (tests that need a failure override this).
    market_fetches: list[str] = []

    async def fake_update(symbol, session_factory=None, client=None):
        market_fetches.append(symbol)
        return market_data.MarketUpdate(symbol, quote=object(), rsi=None, snapshot_id=None)

    monkeypatch.setattr(market_data, "update_market_snapshot", fake_update)
    install.calls = calls
    install.market_fetches = market_fetches
    return install


# ---------------- graph shape ----------------

def test_graph_fans_out_from_prepare_and_in_to_aggregate():
    graph = build_graph().get_graph()
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("__start__", "prepare") in edges and ("aggregate", "__end__") in edges
    for name in AGENT_NAMES:
        assert ("prepare", name) in edges and (name, "aggregate") in edges
    assert len(AGENT_NAMES) == 5


# ---------------- behaviour with fake agents ----------------

async def test_agents_run_in_parallel_and_outputs_are_keyed_by_name(pg_sessionmaker, user, fakes):
    await user()
    start = time.perf_counter()
    result = await run_analysis(1, "infy", pg_sessionmaker)
    elapsed = time.perf_counter() - start

    # five 0.5 s agents: ~0.5 s in parallel vs 2.5 s sequential; generous margin for a busy laptop
    assert elapsed < 1.6
    assert set(result["agents"]) == set(AGENT_NAMES)
    assert result["symbol"] == "INFY.NS" and result["user_id"] == 1 and result["company_name"] == "Infosys Limited"
    assert result["signals"] == {name: 0.5 for name in AGENT_NAMES}
    assert result["statuses"] == {name: "ok" for name in AGENT_NAMES} and result["errors"] == {}
    assert set(result["timings_ms"]) == set(AGENT_NAMES) | {"total"}
    assert result["started_at"] and result["finished_at"]


async def test_each_agent_gets_the_right_inputs(pg_sessionmaker, user, fakes):
    await user()
    await run_analysis(1, "INFY.NS", pg_sessionmaker)
    calls = {name: (args, kwargs) for name, args, kwargs in fakes.calls}
    assert calls["news_agent"] == (("INFY.NS",), {"company_name": "Infosys Limited"})
    assert calls["market_agent"] == (("INFY.NS",), {})
    assert calls["portfolio_agent"] == ((1, "INFY.NS"), {})
    assert calls["user_profiling_agent"] == ((1,), {})
    assert calls["fundamental_economic_agent"] == (("INFY.NS",), {})


async def test_one_failing_agent_does_not_stop_the_others(pg_sessionmaker, user, fakes):
    await user()
    fakes(news_agent=fake_agent_class("news_agent", fail=RuntimeError("chroma folder missing")))
    result = await run_analysis(1, "INFY.NS", pg_sessionmaker)

    news = result["agents"]["news_agent"]
    assert (news["status"], news["signal"], news["confidence"]) == ("error", 0.0, 0.0)
    assert result["errors"] == {"news_agent": "RuntimeError: chroma folder missing"}
    assert all(result["statuses"][n] == "ok" for n in AGENT_NAMES if n != "news_agent")


async def test_slow_agent_times_out(pg_sessionmaker, user, fakes, monkeypatch):
    await user()
    monkeypatch.setattr(orch, "AGENT_TIMEOUT", 0.1)
    fakes(market_agent=fake_agent_class("market_agent", delay=5))
    result = await run_analysis(1, "INFY.NS", pg_sessionmaker)
    assert result["statuses"]["market_agent"] == "timeout"
    assert result["errors"]["market_agent"].startswith("timed out")


async def test_permission_violation_is_isolated(pg_sessionmaker, user, fakes):
    from app.security.permissions import AgentPermissionError

    await user()
    fakes(portfolio_agent=fake_agent_class(
        "portfolio_agent", delay=0, fail=AgentPermissionError("portfolio_agent", "write", "recommendations")))
    result = await run_analysis(1, "INFY.NS", pg_sessionmaker)
    assert result["statuses"]["portfolio_agent"] == "error"
    assert "AgentPermissionError" in result["errors"]["portfolio_agent"]


async def test_unknown_user(pg_sessionmaker, fakes):
    with pytest.raises(UnknownUserError):
        await run_analysis(404, "INFY.NS", pg_sessionmaker)
    assert fakes.calls == []  # no agent ran


async def test_market_data_is_fetched_on_demand_for_a_stock_without_fresh_prices(pg_sessionmaker, user, fakes):
    await user()
    await run_analysis(1, "TCS.NS", pg_sessionmaker)
    assert fakes.market_fetches == ["TCS.NS"]          # no stored price -> fetched now (audit: was "no_data")


async def test_fresh_stored_price_is_not_refetched(pg_sessionmaker, user, fakes):
    await user()
    async with pg_sessionmaker() as db:
        db.add(MarketSnapshot(symbol="INFY.NS", price=Decimal(1500), source="yfinance",
                              fetched_at=datetime.now(UTC) - timedelta(minutes=5)))
        await db.commit()
    await run_analysis(1, "INFY.NS", pg_sessionmaker)
    assert fakes.market_fetches == []


async def test_unknown_symbol_is_rejected_before_any_agent_runs(pg_sessionmaker, user, fakes, monkeypatch):
    await user()

    async def no_price(symbol, session_factory=None, client=None):
        return market_data.MarketUpdate(symbol, quote=None, rsi=None, snapshot_id=None)

    monkeypatch.setattr(market_data, "update_market_snapshot", no_price)
    with pytest.raises(UnknownSymbolError, match="ZZNODATA.NS"):
        await run_analysis(1, "ZZNODATA", pg_sessionmaker)
    assert fakes.calls == []


async def test_stale_price_is_used_when_the_refresh_fails(pg_sessionmaker, user, fakes, monkeypatch):
    await user()
    async with pg_sessionmaker() as db:
        db.add(MarketSnapshot(symbol="INFY.NS", price=Decimal(1500), source="yfinance",
                              fetched_at=datetime.now(UTC) - timedelta(days=2)))
        await db.commit()

    async def no_price(symbol, session_factory=None, client=None):
        return market_data.MarketUpdate(symbol, quote=None, rsi=None, snapshot_id=None)

    monkeypatch.setattr(market_data, "update_market_snapshot", no_price)
    result = await run_analysis(1, "INFY.NS", pg_sessionmaker)   # Yahoo down is not "unknown symbol"
    assert result["statuses"]["market_agent"] == "ok"


async def test_company_name_lookup_failure_is_not_fatal(pg_sessionmaker, user, fakes, monkeypatch):
    await user()

    async def broken(symbol, session_factory):
        raise ConnectionError("yahoo down")

    monkeypatch.setattr(fundamentals, "refresh_if_stale", broken)
    result = await run_analysis(1, "INFY.NS", pg_sessionmaker)
    assert result["company_name"] is None and result["statuses"]["news_agent"] == "ok"


# ---------------- end to end with the five REAL agents ----------------

async def test_end_to_end_with_real_agents(pg_sessionmaker, user, chroma, fake_model, monkeypatch):
    await user()
    now = datetime.now(UTC)
    async with pg_sessionmaker() as db:
        db.add(PortfolioHolding(user_id=1, asset_type=AssetType.STOCK, symbol="INFY.NS", quantity=Decimal(10),
                                avg_buy_price=Decimal(1400), source=TransactionSource.MANUAL))
        db.add(MarketSnapshot(symbol="INFY.NS", price=Decimal(1500), source="yfinance", fetched_at=now))
        for i in range(20):
            db.add(PriceHistory(symbol="INFY.NS", date=date.today() - timedelta(days=19 - i),
                                close=Decimal(1400 + i * 5), source="yfinance"))
        db.add(CompanyFundamentals(symbol="INFY.NS", name="Infosys Limited", sector="Technology", pe_ratio=13.3,
                                   eps=77.8, roe=0.32, revenue_growth=0.03, source="yfinance", fetched_at=now))
        await db.commit()

    async def no_llm(*args, **kwargs):
        raise llm.LLMNotConfigured("GEMINI_API_KEY is not set")

    monkeypatch.setattr(llm, "complete", no_llm)

    result = await run_analysis(1, "INFY.NS", pg_sessionmaker)

    assert result["company_name"] == "Infosys Limited"            # from the fresh fundamentals cache
    assert result["statuses"] == {
        "news_agent": "no_news",                                    # empty vector store
        "market_agent": "ok",
        "portfolio_agent": "ok",
        "user_profiling_agent": "insufficient_history",
        "fundamental_economic_agent": "ok",
    }
    assert result["errors"] == {}
    assert result["agents"]["market_agent"]["trend"] == "up"
    assert result["agents"]["portfolio_agent"]["unrealized_pl"] == 1000.0
    assert result["agents"]["fundamental_economic_agent"]["valuation"] == "cheap"
    assert result["agents"]["user_profiling_agent"]["risk_appetite"] == "moderate"
    async with pg_sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(AgentLog)) == 5   # every agent logged its call
