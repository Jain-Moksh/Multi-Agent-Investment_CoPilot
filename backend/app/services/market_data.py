"""
Market data for Indian equities from three sources:

    yfinance      - primary: live-ish price, day change, 30-day OHLCV history
    NSE (nsepython) - fallback when yfinance fails (NSE often blocks scripts,
                      so this can fail too)
    Alpha Vantage - RSI-14; free tier = 25 requests/day, so results are
                    cached in technical_indicators for 6 hours

yfinance and nsepython are synchronous libraries, so they run in a worker
thread (asyncio.to_thread) to avoid blocking FastAPI's event loop.

No function here raises on a data-source failure: errors are logged and
None is returned, so one bad symbol or API outage can't stop the pipeline.
"""

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models import MarketSnapshot, PriceHistory, TechnicalIndicator
from app.services import key_pool
from app.services.http_utils import http_client, safe_get

logger = logging.getLogger(__name__)

HISTORY_PERIOD = "1mo"                 # ~30 calendar days = ~21 trading days
NSE_TIMEOUT = 20.0                     # seconds; nsepython has no timeout of its own

ALPHAVANTAGE_URL = "https://www.alphavantage.co/query"
RSI_INDICATOR = "RSI_14"
RSI_PERIOD = 14
RSI_CACHE_MAX_AGE = timedelta(hours=6)
# After Alpha Vantage says "rate limit reached", don't call it again for a while.
ALPHAVANTAGE_COOLDOWN = timedelta(hours=1)
_alphavantage_blocked_until: datetime | None = None


@dataclass
class Quote:
    symbol: str
    price: float
    change_pct: float | None
    volume: int | None
    source: str                              # "yfinance" | "nse"
    history: pd.DataFrame | None = None      # Open/High/Low/Close/Volume, yfinance only
    industry: str | None = None              # NSE only


@dataclass
class RSIReading:
    symbol: str
    value: float
    as_of: date               # trading day the RSI refers to
    fetched_at: datetime      # when it was fetched from Alpha Vantage
    from_cache: bool
    stale: bool = False       # True = older than 6 h, returned because a refresh wasn't possible


class AlphaVantageRateLimitError(Exception):
    """Alpha Vantage answered with its daily/minute rate-limit message."""


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _base_symbol(symbol: str) -> str:
    """'RELIANCE.NS' -> 'RELIANCE' (NSE's own API uses bare symbols)."""
    return symbol.split(".")[0].upper()


# ======================================================================
# yfinance (primary)
# ======================================================================

def _yfinance_quote_sync(symbol: str) -> Quote | None:
    import yfinance as yf  # imported lazily: slow import, only needed here

    ticker = yf.Ticker(symbol)
    history = ticker.history(period=HISTORY_PERIOD, interval="1d", auto_adjust=False)
    if history.empty:  # unknown / delisted symbol
        logger.error("[yfinance] no data for %s", symbol)
        return None
    history = history[["Open", "High", "Low", "Close", "Volume"]]

    # fast_info gives the latest traded price; fall back to the last two daily closes.
    try:
        price = ticker.fast_info["last_price"]
        prev_close = ticker.fast_info["previous_close"]
    except Exception:  # yfinance raises assorted errors here
        price = prev_close = None
    if not _is_number(price):
        price = float(history["Close"].iloc[-1])
    if not _is_number(prev_close):
        prev_close = float(history["Close"].iloc[-2]) if len(history) > 1 else None

    change_pct = (price - prev_close) / prev_close * 100 if prev_close else None
    volume = history["Volume"].iloc[-1]
    return Quote(
        symbol=symbol,
        price=float(price),
        change_pct=round(change_pct, 4) if change_pct is not None else None,
        volume=int(volume) if _is_number(float(volume)) else None,
        source="yfinance",
        history=history,
    )


async def fetch_yfinance_quote(symbol: str) -> Quote | None:
    """
    Current price, day change % and last ~30 days of daily OHLCV for an
    NSE/BSE symbol such as "RELIANCE.NS". Returns None on any failure.
    """
    try:
        return await asyncio.to_thread(_yfinance_quote_sync, symbol)
    except Exception as exc:  # network errors, Yahoo rate limits (YFRateLimitError), parsing issues
        logger.error("[yfinance] %s failed: %s: %s", symbol, type(exc).__name__, exc)
        return None


# ======================================================================
# NSE via nsepython (fallback)
# ======================================================================

def _nse_eq_sync(base_symbol: str) -> dict[str, Any]:
    from nsepython import nse_eq  # imported lazily: heavy import

    return nse_eq(base_symbol)


async def fetch_nse_quote(symbol: str) -> dict[str, Any] | None:
    """
    NSE's quote for "RELIANCE" / "RELIANCE.NS".
    Returns {"priceInfo": {...lastPrice, change, pChange, previousClose...}, "industry": str | None},
    or None on failure (NSE frequently blocks automated requests and then returns {}).
    """
    base = _base_symbol(symbol)
    try:
        data = await asyncio.wait_for(asyncio.to_thread(_nse_eq_sync, base), timeout=NSE_TIMEOUT)
    except TimeoutError:
        logger.error("[nse] %s timed out after %.0fs", base, NSE_TIMEOUT)
        return None
    except Exception as exc:
        logger.error("[nse] %s failed: %s: %s", base, type(exc).__name__, exc)
        return None

    price_info = data.get("priceInfo") if isinstance(data, dict) else None
    if not price_info or not _is_number(price_info.get("lastPrice")):
        logger.error("[nse] no price data for %s (empty response - NSE may be blocking requests)", base)
        return None
    return {"priceInfo": price_info, "industry": (data.get("info") or {}).get("industry")}


def _quote_from_nse(symbol: str, nse: dict[str, Any]) -> Quote:
    price_info = nse["priceInfo"]
    change_pct = price_info.get("pChange")
    return Quote(
        symbol=symbol,
        price=float(price_info["lastPrice"]),
        change_pct=round(float(change_pct), 4) if _is_number(change_pct) else None,
        volume=None,  # nse_eq's priceInfo has no traded volume
        source="nse",
        industry=nse.get("industry"),
    )


# ======================================================================
# Alpha Vantage RSI (cached)
# ======================================================================

def _alphavantage_symbol(symbol: str) -> str:
    """
    Alpha Vantage lists Indian stocks under BSE with a ".BSE" suffix
    ("RELIANCE.NS" -> "RELIANCE.BSE"); NSE suffixes are not supported.
    """
    return f"{_base_symbol(symbol)}.BSE"


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def alphavantage_available(purpose: str) -> bool:
    """
    True if Alpha Vantage may be called now: a key is set, at least one key is not resting
    after a rate limit, and we are not in the all-keys cooldown. Shared by all AV callers.
    """
    if not settings.api_keys("alphavantage"):
        logger.warning("[alphavantage] ALPHAVANTAGE_API_KEY(S) not set - skipping %s", purpose)
        return False
    if _alphavantage_blocked_until and datetime.now(UTC) < _alphavantage_blocked_until:
        logger.info("[alphavantage] in rate-limit cooldown - skipping %s", purpose)
        return False
    if not key_pool.usable_keys("alphavantage"):
        logger.info("[alphavantage] every key is resting after a rate limit - skipping %s", purpose)
        return False
    return True


def start_alphavantage_cooldown(message: str) -> None:
    """Called when EVERY key hit its rate limit: pause all Alpha Vantage calls for a while."""
    global _alphavantage_blocked_until
    _alphavantage_blocked_until = datetime.now(UTC) + ALPHAVANTAGE_COOLDOWN
    logger.warning(
        "[alphavantage] rate limit reached on every key; pausing calls until %s. API said: %s",
        _alphavantage_blocked_until.isoformat(timespec="minutes"), message[:150],
    )


async def alphavantage_query(client: httpx.AsyncClient, params: dict[str, Any], label: str) -> dict[str, Any] | None:
    """
    One Alpha Vantage request (the API key is added here). Keys are tried in order: a key that
    hits its rate limit is rested (key_pool) and the next key is used. Returns the JSON body, or
    None for errors / unknown symbols. Raises AlphaVantageRateLimitError when every key is limited.
    """
    rate_limit_message = None
    for key in key_pool.usable_keys("alphavantage"):
        response = await safe_get(client, "alphavantage", ALPHAVANTAGE_URL, params | {"apikey": key})
        if response is None:
            return None
        try:
            payload = response.json()
        except ValueError:
            logger.error("[alphavantage] non-JSON response for %s", label)
            return None

        # Alpha Vantage returns HTTP 200 even for errors; the body tells us what happened.
        # Rate limits come back as {"Note": ...} (older) or {"Information": ...} (newer).
        message = payload.get("Note") or payload.get("Information")
        if message:
            if "rate limit" in message.lower() or "call frequency" in message.lower():
                key_pool.report_failure("alphavantage", key, key_pool.classify(429, message), message)
                rate_limit_message = message
                continue                                    # same request, next key
            logger.error("[alphavantage] %s: %s", label, message[:200])
            return None
        if "Error Message" in payload:
            logger.error("[alphavantage] %s: %s", label, payload["Error Message"][:200])
            return None
        key_pool.report_success("alphavantage", key)
        return payload
    if rate_limit_message is not None:
        raise AlphaVantageRateLimitError(rate_limit_message)
    return None


async def _call_alphavantage_rsi(client: httpx.AsyncClient, symbol: str) -> tuple[float, date] | None:
    """
    One API call. Returns (rsi, as_of), or None for errors / unknown symbols.
    Raises AlphaVantageRateLimitError when the quota is exhausted.
    """
    params = {
        "function": "RSI",
        "symbol": _alphavantage_symbol(symbol),
        "interval": "daily",
        "time_period": RSI_PERIOD,
        "series_type": "close",
    }
    payload = await alphavantage_query(client, params, symbol)
    if payload is None:
        return None

    series = payload.get("Technical Analysis: RSI") or {}
    if not series:
        logger.error("[alphavantage] no RSI data for %s", symbol)
        return None
    latest_day = max(series)  # keys are "YYYY-MM-DD", so max() = most recent
    try:
        return float(series[latest_day]["RSI"]), date.fromisoformat(latest_day)
    except (KeyError, ValueError):
        logger.error("[alphavantage] malformed RSI entry for %s", symbol)
        return None


async def fetch_alphavantage_rsi(
    symbol: str,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    client: httpx.AsyncClient | None = None,
) -> RSIReading | None:
    """
    Latest daily RSI-14 for `symbol`.

    1. If a cached value is younger than 6 h, return it (no API call).
    2. Otherwise call Alpha Vantage and save the result to the cache.
    3. If the call is impossible (no key, rate limit, error), return the
       stale cached value if there is one (stale=True), else None.
    """
    now = datetime.now(UTC)

    async with session_factory() as db:
        cached = await db.scalar(
            select(TechnicalIndicator).where(
                TechnicalIndicator.symbol == symbol, TechnicalIndicator.indicator == RSI_INDICATOR
            )
        )

    def from_cache(stale: bool) -> RSIReading | None:
        if cached is None:
            return None
        return RSIReading(symbol, cached.value, cached.as_of, _as_utc(cached.fetched_at), True, stale)

    if cached is not None and now - _as_utc(cached.fetched_at) < RSI_CACHE_MAX_AGE:
        return from_cache(stale=False)

    if not alphavantage_available(f"RSI for {symbol}"):
        return from_cache(stale=True)

    try:
        async with http_client(client) as http:
            result = await _call_alphavantage_rsi(http, symbol)
    except AlphaVantageRateLimitError as exc:
        start_alphavantage_cooldown(str(exc))
        return from_cache(stale=True)

    if result is None:
        return from_cache(stale=True)

    value, as_of = result
    async with session_factory() as db:
        values = {"symbol": symbol, "indicator": RSI_INDICATOR, "value": value,
                  "as_of": as_of, "source": "alphavantage", "fetched_at": now}
        await db.execute(
            pg_insert(TechnicalIndicator)
            .values(**values)
            .on_conflict_do_update(index_elements=["symbol", "indicator"], set_=values)
        )
        await db.commit()
    logger.info("[alphavantage] %s RSI-14 = %.2f (as of %s)", symbol, value, as_of)
    return RSIReading(symbol, value, as_of, now, from_cache=False)


# ======================================================================
# Combined update
# ======================================================================

def _decimal_or_none(value: Any) -> Decimal | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return Decimal(str(round(number, 4))) if math.isfinite(number) else None


async def save_price_history(
    symbol: str, history: pd.DataFrame, session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal
) -> int:
    """
    Upsert daily OHLCV bars (yfinance history) into price_history, one row per
    (symbol, trading day); a re-fetched day overwrites the stored one (today's
    bar changes during market hours). Returns the number of bars written.
    """
    rows = []
    for timestamp, bar in history.iterrows():
        close = _decimal_or_none(bar.get("Close"))
        if close is None:
            continue
        volume = bar.get("Volume")
        rows.append({
            "symbol": symbol,
            "date": pd.Timestamp(timestamp).date(),
            "open": _decimal_or_none(bar.get("Open")),
            "high": _decimal_or_none(bar.get("High")),
            "low": _decimal_or_none(bar.get("Low")),
            "close": close,
            "volume": int(volume) if _is_number(float(volume)) else None,
            "source": "yfinance",
            "fetched_at": datetime.now(UTC),
        })
    if not rows:
        return 0
    async with session_factory() as db:
        stmt = pg_insert(PriceHistory).values(rows)
        await db.execute(
            stmt.on_conflict_do_update(
                constraint="uq_price_history_symbol_date",
                set_={col: stmt.excluded[col] for col in ("open", "high", "low", "close", "volume", "source", "fetched_at")},
            )
        )
        await db.commit()
    return len(rows)


@dataclass
class MarketUpdate:
    symbol: str
    quote: Quote | None          # None = both price sources failed
    rsi: RSIReading | None
    snapshot_id: int | None      # id of the new market_snapshots row
    history_bars: int = 0        # daily bars saved to price_history


async def update_market_snapshot(
    symbol: str,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    client: httpx.AsyncClient | None = None,
) -> MarketUpdate:
    """
    Refresh market data for one symbol:
      price: yfinance, falling back to NSE -> saved as a market_snapshots row
      RSI:   Alpha Vantage via the 6-hour cache -> technical_indicators
    Never raises for data-source problems; check the returned MarketUpdate.
    """
    quote = await fetch_yfinance_quote(symbol)
    if quote is None:
        logger.warning("[market] yfinance failed for %s, trying NSE", symbol)
        nse = await fetch_nse_quote(symbol)
        quote = _quote_from_nse(symbol, nse) if nse else None

    if quote is None:
        # No price = unknown ticker or every source down: don't spend an Alpha Vantage call
        # (25/day) on it either.
        logger.error("[market] no price available for %s from any source", symbol)
        return MarketUpdate(symbol, None, None, None)

    try:
        rsi = await fetch_alphavantage_rsi(symbol, session_factory, client)
    except Exception:  # RSI is optional: never let it stop the price update
        logger.exception("[market] RSI lookup crashed for %s", symbol)
        rsi = None

    async with session_factory() as db:
        snapshot = MarketSnapshot(
            symbol=symbol,
            price=Decimal(str(round(quote.price, 4))),
            change_pct=quote.change_pct,
            volume=quote.volume,
            source=quote.source,
        )
        db.add(snapshot)
        await db.commit()

    history_bars = 0
    if quote.history is not None:
        try:
            history_bars = await save_price_history(symbol, quote.history, session_factory)
        except Exception:  # history is a bonus: never lose the snapshot over it
            logger.exception("[market] could not save price history for %s", symbol)

    logger.info(
        "[market] %s = %.2f (%s%%) via %s, RSI=%s",
        symbol, quote.price, quote.change_pct, quote.source, f"{rsi.value:.1f}" if rsi else "n/a",
    )
    return MarketUpdate(symbol, quote, rsi, snapshot.id, history_bars)
