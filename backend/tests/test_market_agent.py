"""
Market Agent: indicator maths (checked against a textbook RSI example) and the
agent end to end on PostgreSQL (TEST_DATABASE_URL). No LLM, no network.
"""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import func, select

from app.agents import market_agent as ma
from app.agents.market_agent import MarketAgent, classify_rsi, classify_trend, compute_rsi, moving_average
from app.models import AgentLog, MarketSnapshot, PriceHistory, TechnicalIndicator
from app.security.permissions import check_permission
from app.services.market_data import save_price_history

# StockCharts' classic RSI worked example (Wilder). Their table shows 70.53 because it
# rounds the intermediate averages; exact arithmetic gives 70.46.
CLASSIC_CLOSES = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
                  45.89, 46.03, 45.61, 46.28, 46.28]
MORE_CLOSES = [46.00, 46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45]


def reference_rsi(closes: list[float], period: int = 14) -> float:
    """Independent implementation: SMA seed, then pandas' Wilder smoothing (ewm alpha=1/period)."""
    delta = pd.Series(closes).diff().dropna()
    gains, losses = delta.clip(lower=0), (-delta).clip(lower=0)
    def wilder(s: pd.Series) -> float:
        seeded = pd.concat([pd.Series([s.iloc[:period].mean()]), s.iloc[period:]], ignore_index=True)
        return float(seeded.ewm(alpha=1 / period, adjust=False).mean().iloc[-1])
    avg_gain, avg_loss = wilder(gains), wilder(losses)
    return 100 - 100 / (1 + avg_gain / avg_loss)


# ---------------- pure maths ----------------

def test_rsi_matches_textbook_example():
    assert compute_rsi(CLASSIC_CLOSES) == pytest.approx(70.46, abs=0.01)
    assert compute_rsi(CLASSIC_CLOSES) == pytest.approx(70.53, abs=0.1)  # StockCharts' rounded figure


@pytest.mark.parametrize("extra", range(len(MORE_CLOSES) + 1))
def test_rsi_matches_independent_implementation(extra):
    closes = CLASSIC_CLOSES + MORE_CLOSES[:extra]
    assert compute_rsi(closes) == pytest.approx(reference_rsi(closes), abs=0.01)


@pytest.mark.parametrize(
    "closes, expected",
    [
        ([float(i) for i in range(1, 17)], 100.0),          # only gains
        ([float(i) for i in range(16, 0, -1)], 0.0),        # only losses
        ([100.0] * 16, 50.0),                               # no movement
        ([100.0] * 14, None),                               # needs 15 closes
    ],
)
def test_rsi_edge_cases(closes, expected):
    assert compute_rsi(closes) == expected


def test_moving_average():
    assert moving_average([1, 2, 3, 4, 5, 6, 7, 8]) == 5.0  # last 7: 2..8
    assert moving_average([1, 2, 3]) is None


@pytest.mark.parametrize("pct, trend", [(2.5, "up"), (-1.5, "down"), (0.9, "flat"), (-1.0, "flat"), (None, "flat")])
def test_classify_trend(pct, trend):
    assert classify_trend(pct) == trend


@pytest.mark.parametrize("rsi, label", [(70, "overbought"), (85, "overbought"), (30, "oversold"), (50, "neutral"),
                                        (None, "neutral")])
def test_classify_rsi(rsi, label):
    assert classify_rsi(rsi) == label


@pytest.mark.parametrize(
    "pct, rsi_signal, expected",
    [(5.0, "neutral", 0.7), (10.0, "neutral", 0.7), (-2.5, "neutral", -0.35),
     (5.0, "overbought", 0.4), (-5.0, "oversold", -0.4), (0.0, "oversold", 0.3)],
)
def test_signal(pct, rsi_signal, expected):
    assert ma.compute_signal(pct, rsi_signal) == expected


def test_confidence_never_exceeds_0_8():
    assert ma.compute_confidence(30, True, timedelta(hours=1)) == 0.8
    assert ma.compute_confidence(8, False, timedelta(days=10)) == 0.3


# ---------------- the agent (PostgreSQL) ----------------

TODAY = date.today()


async def seed_history(session_factory, symbol: str, closes: list[float], end: date = TODAY) -> None:
    async with session_factory() as db:
        for i, close in enumerate(closes):
            day = end - timedelta(days=len(closes) - 1 - i)
            db.add(PriceHistory(symbol=symbol, date=day, close=Decimal(str(close)), source="test"))
        await db.commit()


async def seed_snapshot(session_factory, symbol: str, price: float, when: datetime | None = None) -> None:
    async with session_factory() as db:
        db.add(MarketSnapshot(symbol=symbol, price=Decimal(str(price)), change_pct=1.2, volume=1000, source="yfinance",
                              fetched_at=when or datetime.now(UTC)))
        await db.commit()


async def last_log(session_factory) -> dict:
    async with session_factory() as db:
        log = await db.scalar(select(AgentLog).order_by(AgentLog.id.desc()))
    return {"agent": log.agent_name, "action": log.action, "output": json.loads(log.output_summary)}


async def test_uptrend_with_computed_rsi(pg_sessionmaker):
    closes = [100 + i for i in range(20)]                 # steady rise 100 -> 119
    await seed_history(pg_sessionmaker, "INFY.NS", closes)
    await seed_snapshot(pg_sessionmaker, "INFY.NS", 122.0)

    r = await MarketAgent(pg_sessionmaker).analyze("infy")

    assert (r["agent"], r["symbol"], r["status"]) == ("market_agent", "INFY.NS", "ok")
    assert r["price"] == 122.0 and r["price_source"] == "snapshot"
    assert r["ma7"] == 116.0 and r["pct_vs_ma7"] == pytest.approx(5.17, abs=0.01)
    assert r["trend"] == "up"
    assert (r["rsi"], r["rsi_source"], r["rsi_signal"]) == (100.0, "computed", "overbought")
    assert r["signal"] == 0.4                               # 0.7 x 1 (capped) + 0.3 x -1
    assert r["confidence"] == 0.8
    assert r["summary"] == ("INFY.NS at ₹122.00 is 5.2% above its 7-day average (₹116.00): uptrend. "
                            "RSI-14 is 100 (overbought, the rise may be stretched).")
    assert r["rationale"] == r["summary"]

    log = await last_log(pg_sessionmaker)
    assert log["agent"] == "market_agent" and log["action"] == "analyze"
    assert log["output"]["trend"] == "up" and log["output"]["rsi_signal"] == "overbought"


async def test_downtrend_prefers_fresh_alpha_vantage_rsi(pg_sessionmaker):
    await seed_history(pg_sessionmaker, "TCS.NS", [200 - i for i in range(20)])  # falling 200 -> 181
    async with pg_sessionmaker() as db:
        db.add(TechnicalIndicator(symbol="TCS.NS", indicator="RSI_14", value=28.4, as_of=TODAY - timedelta(days=1),
                                  source="alphavantage", fetched_at=datetime.now(UTC)))
        await db.commit()

    r = await MarketAgent(pg_sessionmaker).analyze("TCS.NS")
    assert r["price_source"] == "history" and r["price"] == 181.0   # no snapshot -> last close
    assert r["trend"] == "down"
    assert (r["rsi"], r["rsi_source"], r["rsi_signal"]) == (28.4, "alphavantage", "oversold")
    assert r["signal"] == pytest.approx(0.7 * -0.33 + 0.3, abs=0.01)  # falling, but oversold softens it


async def test_stale_alpha_vantage_rsi_is_replaced_by_computed(pg_sessionmaker):
    await seed_history(pg_sessionmaker, "WIPRO.NS", CLASSIC_CLOSES)
    async with pg_sessionmaker() as db:
        db.add(TechnicalIndicator(symbol="WIPRO.NS", indicator="RSI_14", value=10.0, as_of=TODAY - timedelta(days=20),
                                  source="alphavantage", fetched_at=datetime.now(UTC) - timedelta(days=20)))
        await db.commit()
    r = await MarketAgent(pg_sessionmaker).analyze("WIPRO.NS")
    assert r["rsi_source"] == "computed" and r["rsi"] == pytest.approx(70.46, abs=0.01)


async def test_flat_market(pg_sessionmaker):
    await seed_history(pg_sessionmaker, "ITC.NS", [400, 401, 399, 400, 402, 398, 400, 401, 399, 400] * 2)
    r = await MarketAgent(pg_sessionmaker).analyze("ITC.NS")
    assert r["trend"] == "flat" and r["rsi_signal"] == "neutral" and abs(r["signal"]) < 0.1


async def test_snapshot_older_than_history_is_ignored(pg_sessionmaker):
    await seed_history(pg_sessionmaker, "HDFCBANK.NS", [1500.0] * 10)
    await seed_snapshot(pg_sessionmaker, "HDFCBANK.NS", 9999.0, when=datetime.now(UTC) - timedelta(days=30))
    r = await MarketAgent(pg_sessionmaker).analyze("HDFCBANK.NS")
    assert r["price"] == 1500.0 and r["price_source"] == "history"


async def test_insufficient_history(pg_sessionmaker):
    await seed_history(pg_sessionmaker, "NEWIPO.NS", [100.0, 104.0, 108.0])
    r = await MarketAgent(pg_sessionmaker).analyze("NEWIPO.NS")
    assert r["status"] == "insufficient_history" and r["trend"] == "flat"
    assert (r["signal"], r["confidence"]) == (0.0, 0.0)
    assert "only 3 day(s) of history" in r["summary"]


async def test_no_data(pg_sessionmaker):
    r = await MarketAgent(pg_sessionmaker).analyze("UNKNOWN.NS")
    assert r["status"] == "no_data" and r["confidence"] == 0.0 and r["price"] is None
    assert (await last_log(pg_sessionmaker))["output"]["status"] == "no_data"


async def test_other_symbols_data_is_not_used(pg_sessionmaker):
    await seed_history(pg_sessionmaker, "TCS.NS", [100 + i for i in range(20)])
    r = await MarketAgent(pg_sessionmaker).analyze("INFY.NS")
    assert r["status"] == "no_data"


# ---------------- price history persistence (market data job) ----------------

async def test_save_price_history_upserts(pg_sessionmaker):
    idx = pd.date_range("2026-09-01", periods=5, freq="B", tz="Asia/Kolkata")
    frame = pd.DataFrame({"Open": [1, 2, 3, 4, 5], "High": [1, 2, 3, 4, 5], "Low": [1, 2, 3, 4, 5],
                          "Close": [10.0, 11.0, float("nan"), 13.0, 14.0], "Volume": [100] * 5}, index=idx)
    assert await save_price_history("INFY.NS", frame, pg_sessionmaker) == 4      # NaN close skipped
    frame.loc[idx[-1], "Close"] = 15.5                                           # today's bar moved
    await save_price_history("INFY.NS", frame, pg_sessionmaker)
    async with pg_sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(PriceHistory)) == 4
        last = await db.scalar(select(PriceHistory).order_by(PriceHistory.date.desc()))
    assert last.date == date(2026, 9, 7) and last.close == Decimal("15.5000")  # 5th business day from Tue 1 Sep


# ---------------- permissions ----------------

def test_reads_are_permission_guarded_and_agent_is_read_only_for_history():
    for method in (MarketAgent._latest_snapshot, MarketAgent._daily_closes, MarketAgent._cached_rsi):
        assert hasattr(method, "__wrapped__")
    assert check_permission("market_agent", "read", "price_history")
    assert not check_permission("market_agent", "write", "price_history")
    for table in ("portfolio_holdings", "transactions", "news_events", "recommendations", "user_profiles"):
        assert not check_permission("market_agent", "read", table)
