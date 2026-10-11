"""
Market data tests. yfinance / nsepython are replaced with fakes and Alpha
Vantage with httpx.MockTransport, so no network or API key is needed.
Tests touching the database need TEST_DATABASE_URL (see conftest.py).

Run from backend/:  pytest tests/test_market_data.py -v
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pandas as pd
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import MarketSnapshot, TechnicalIndicator
from app.services import market_data as md

RSI_JSON = {
    "Meta Data": {"1: Symbol": "RELIANCE.BSE"},
    "Technical Analysis: RSI": {
        "2026-10-01": {"RSI": "61.2345"},
        "2026-09-30": {"RSI": "58.0000"},
    },
}
RATE_LIMIT_JSON = {
    "Information": "We have detected your API key as ... Our standard API rate limit is 25 requests per day."
}


def fake_history() -> pd.DataFrame:
    idx = pd.date_range("2026-09-01", periods=22, freq="B", tz="Asia/Kolkata")
    closes = [1000 + i for i in range(22)]
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [5_000_000] * 22},
        index=idx,
    )


def fake_yf_quote(symbol: str) -> md.Quote:
    return md.Quote(symbol, 1021.0, 0.098, 5_000_000, "yfinance", history=fake_history())


NSE_RESPONSE = {
    "priceInfo": {"lastPrice": 1180.5, "change": -6.5, "pChange": -0.5476, "previousClose": 1187.0},
    "info": {"industry": "Refineries & Marketing"},
}


class Counter:
    """MockTransport handler that counts calls and replays one canned JSON body."""

    def __init__(self, body: dict):
        self.body, self.calls, self.params = body, 0, None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.params = dict(request.url.params)
        return httpx.Response(200, json=self.body)


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    monkeypatch.setattr(settings, "ALPHAVANTAGE_API_KEY", "test-av-key")
    monkeypatch.setattr(md, "_alphavantage_blocked_until", None)


# ======================================================================
# yfinance
# ======================================================================

class FakeTicker:
    def __init__(self, history: pd.DataFrame, fast_info: dict | None):
        self._history, self._fast_info = history, fast_info

    def history(self, **kwargs):
        return self._history

    @property
    def fast_info(self):
        if self._fast_info is None:
            raise KeyError("fast_info unavailable")
        return self._fast_info


def patch_yfinance(monkeypatch, history, fast_info):
    import yfinance

    monkeypatch.setattr(yfinance, "Ticker", lambda symbol: FakeTicker(history, fast_info))


async def test_yfinance_quote_uses_fast_info(monkeypatch):
    patch_yfinance(monkeypatch, fake_history(), {"last_price": 1100.0, "previous_close": 1000.0})
    q = await md.fetch_yfinance_quote("RELIANCE.NS")
    assert q.price == 1100.0 and q.change_pct == 10.0
    assert q.volume == 5_000_000 and q.source == "yfinance"
    assert list(q.history.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(q.history) == 22


async def test_yfinance_quote_falls_back_to_history_closes(monkeypatch):
    patch_yfinance(monkeypatch, fake_history(), fast_info=None)
    q = await md.fetch_yfinance_quote("RELIANCE.NS")
    assert q.price == 1021.0                         # last close
    assert q.change_pct == round(1 / 1020 * 100, 4)  # vs previous close


async def test_yfinance_unknown_symbol_returns_none(monkeypatch):
    patch_yfinance(monkeypatch, pd.DataFrame(), fast_info=None)
    assert await md.fetch_yfinance_quote("NOTREAL.NS") is None


async def test_yfinance_exception_returns_none(monkeypatch):
    def boom(symbol):
        raise ConnectionError("Yahoo down")

    monkeypatch.setattr(md, "_yfinance_quote_sync", boom)
    assert await md.fetch_yfinance_quote("RELIANCE.NS") is None


# ======================================================================
# NSE
# ======================================================================

async def test_nse_quote_strips_suffix_and_returns_price_info(monkeypatch):
    seen = {}

    def fake_nse_eq(base):
        seen["symbol"] = base
        return NSE_RESPONSE

    monkeypatch.setattr(md, "_nse_eq_sync", fake_nse_eq)
    result = await md.fetch_nse_quote("RELIANCE.NS")
    assert seen["symbol"] == "RELIANCE"
    assert result == {"priceInfo": NSE_RESPONSE["priceInfo"], "industry": "Refineries & Marketing"}


@pytest.mark.parametrize("response", [{}, {"priceInfo": {}}, {"priceInfo": {"lastPrice": None}}])
async def test_nse_empty_response_returns_none(monkeypatch, response):
    monkeypatch.setattr(md, "_nse_eq_sync", lambda base: response)
    assert await md.fetch_nse_quote("RELIANCE.NS") is None


async def test_nse_timeout_returns_none(monkeypatch):
    import time

    monkeypatch.setattr(md, "NSE_TIMEOUT", 0.1)
    monkeypatch.setattr(md, "_nse_eq_sync", lambda base: time.sleep(1) or NSE_RESPONSE)
    assert await md.fetch_nse_quote("RELIANCE.NS") is None


# ======================================================================
# Alpha Vantage RSI + cache (needs PostgreSQL)
# ======================================================================

async def test_rsi_fetches_then_serves_from_cache(pg_sessionmaker):
    handler = Counter(RSI_JSON)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await md.fetch_alphavantage_rsi("RELIANCE.NS", pg_sessionmaker, client)
        second = await md.fetch_alphavantage_rsi("RELIANCE.NS", pg_sessionmaker, client)

    assert handler.calls == 1                       # second call served from cache
    assert handler.params["symbol"] == "RELIANCE.BSE"
    assert first.value == 61.2345 and first.as_of == date(2026, 10, 1) and not first.from_cache
    assert second.value == 61.2345 and second.from_cache and not second.stale


async def test_rsi_refetches_when_cache_older_than_6h(pg_sessionmaker):
    async with pg_sessionmaker() as db:
        db.add(TechnicalIndicator(symbol="TCS.NS", indicator="RSI_14", value=40.0, as_of=date(2026, 9, 1),
                                  source="alphavantage", fetched_at=datetime.now(UTC) - timedelta(hours=7)))
        await db.commit()

    handler = Counter(RSI_JSON)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reading = await md.fetch_alphavantage_rsi("TCS.NS", pg_sessionmaker, client)

    assert handler.calls == 1 and reading.value == 61.2345
    async with pg_sessionmaker() as db:
        rows = (await db.scalars(select(TechnicalIndicator))).all()
    assert len(rows) == 1 and rows[0].value == 61.2345  # upserted, not duplicated


async def test_rsi_rate_limit_returns_stale_cache_and_pauses_calls(pg_sessionmaker, caplog):
    async with pg_sessionmaker() as db:
        db.add(TechnicalIndicator(symbol="INFY.NS", indicator="RSI_14", value=45.0, as_of=date(2026, 9, 30),
                                  source="alphavantage", fetched_at=datetime.now(UTC) - timedelta(hours=8)))
        await db.commit()

    handler = Counter(RATE_LIMIT_JSON)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await md.fetch_alphavantage_rsi("INFY.NS", pg_sessionmaker, client)
        second = await md.fetch_alphavantage_rsi("INFY.NS", pg_sessionmaker, client)

    assert first.value == 45.0 and first.stale       # old value, flagged as stale
    assert second.stale and handler.calls == 1       # cooldown: no second API call
    assert "rate limit reached" in caplog.text
    assert "test-av-key" not in caplog.text


async def test_rsi_rate_limit_without_cache_returns_none(pg_sessionmaker):
    async with httpx.AsyncClient(transport=httpx.MockTransport(Counter(RATE_LIMIT_JSON))) as client:
        assert await md.fetch_alphavantage_rsi("WIPRO.NS", pg_sessionmaker, client) is None


@pytest.mark.parametrize("body", [{"Error Message": "Invalid API call."}, {}])
async def test_rsi_api_error_returns_none(pg_sessionmaker, body):
    async with httpx.AsyncClient(transport=httpx.MockTransport(Counter(body))) as client:
        assert await md.fetch_alphavantage_rsi("RELIANCE.NS", pg_sessionmaker, client) is None


async def test_rsi_without_key_makes_no_request(pg_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "ALPHAVANTAGE_API_KEY", "")
    handler = Counter(RSI_JSON)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await md.fetch_alphavantage_rsi("RELIANCE.NS", pg_sessionmaker, client) is None
    assert handler.calls == 0


# ======================================================================
# update_market_snapshot (needs PostgreSQL)
# ======================================================================

async def latest_snapshot(session_factory) -> MarketSnapshot | None:
    async with session_factory() as db:
        return await db.scalar(select(MarketSnapshot).order_by(MarketSnapshot.id.desc()))


async def test_update_uses_yfinance_and_writes_snapshot(pg_sessionmaker, monkeypatch):
    monkeypatch.setattr(md, "_yfinance_quote_sync", fake_yf_quote)
    monkeypatch.setattr(md, "_nse_eq_sync", lambda base: pytest.fail("NSE must not be called"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(Counter(RSI_JSON))) as client:
        update = await md.update_market_snapshot("RELIANCE.NS", pg_sessionmaker, client)

    assert update.quote.source == "yfinance" and update.rsi.value == 61.2345
    row = await latest_snapshot(pg_sessionmaker)
    assert row.id == update.snapshot_id
    assert (row.symbol, row.price, row.volume, row.source) == ("RELIANCE.NS", Decimal("1021.0000"), 5_000_000, "yfinance")


async def test_update_falls_back_to_nse(pg_sessionmaker, monkeypatch):
    monkeypatch.setattr(md, "_yfinance_quote_sync", lambda symbol: None)
    monkeypatch.setattr(md, "_nse_eq_sync", lambda base: NSE_RESPONSE)

    async with httpx.AsyncClient(transport=httpx.MockTransport(Counter(RSI_JSON))) as client:
        update = await md.update_market_snapshot("RELIANCE.NS", pg_sessionmaker, client)

    assert update.quote.source == "nse" and update.quote.industry == "Refineries & Marketing"
    row = await latest_snapshot(pg_sessionmaker)
    assert (row.price, row.change_pct, row.volume, row.source) == (Decimal("1180.5000"), -0.5476, None, "nse")


async def test_update_survives_rate_limited_rsi(pg_sessionmaker, monkeypatch):
    monkeypatch.setattr(md, "_yfinance_quote_sync", fake_yf_quote)

    async with httpx.AsyncClient(transport=httpx.MockTransport(Counter(RATE_LIMIT_JSON))) as client:
        update = await md.update_market_snapshot("RELIANCE.NS", pg_sessionmaker, client)

    assert update.rsi is None and update.snapshot_id is not None  # price still saved


async def test_update_survives_crashing_rsi(pg_sessionmaker, monkeypatch):
    monkeypatch.setattr(md, "_yfinance_quote_sync", fake_yf_quote)

    async def crash(*args, **kwargs):
        raise RuntimeError("unexpected bug")

    monkeypatch.setattr(md, "fetch_alphavantage_rsi", crash)
    update = await md.update_market_snapshot("RELIANCE.NS", pg_sessionmaker)
    assert update.rsi is None and update.snapshot_id is not None


async def test_update_when_all_price_sources_fail(pg_sessionmaker, monkeypatch):
    monkeypatch.setattr(md, "_yfinance_quote_sync", lambda symbol: None)
    monkeypatch.setattr(md, "_nse_eq_sync", lambda base: {})

    counter = Counter(RSI_JSON)
    async with httpx.AsyncClient(transport=httpx.MockTransport(counter)) as client:
        update = await md.update_market_snapshot("RELIANCE.NS", pg_sessionmaker, client)

    assert update.quote is None and update.snapshot_id is None
    assert await latest_snapshot(pg_sessionmaker) is None  # nothing written
    assert counter.calls == 0 and update.rsi is None       # no Alpha Vantage call wasted on an unknown symbol
