"""
Company fundamentals (P/E, sector, ROE, ...) with a one-week database cache.

    row = await refresh_if_stale("INFY.NS")    # returns the cached / refreshed values

Sources, in order:
  1. yfinance `Ticker.info`: free, no key, good coverage of NSE stocks (verified live).
  2. Alpha Vantage OVERVIEW: fallback only if yfinance fails and a key is set. Shares
     the RSI call's rate-limit cooldown. Coverage of Indian (".BSE") symbols is
     unverified until a key exists.

Units are normalised before storing, because the two sources differ:
  - debt_to_equity is stored as a ratio (yfinance reports a percentage: 46.3 -> 0.463)
  - dividend_yield_pct is a percentage (Alpha Vantage reports a fraction: 0.035 -> 3.5)
  - roe / profit_margin / revenue_growth are fractions (0.32 = 32%)

This is a system service (like the market data job), not an agent: it writes
company_fundamentals. Agents only read that table through their own permissions.
"""

import asyncio
import logging
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import AsyncSessionLocal
from app.models import CompanyFundamentals
from app.services import market_data
from app.services.http_utils import http_client

logger = logging.getLogger(__name__)

CACHE_MAX_AGE = timedelta(days=7)
YFINANCE_TIMEOUT = 20.0

COLUMNS = ("name", "sector", "industry", "currency", "market_cap", "pe_ratio", "forward_pe", "price_to_book", "eps",
           "roe", "debt_to_equity", "dividend_yield_pct", "profit_margin", "revenue_growth", "week52_high",
           "week52_low")


def _num(value: Any) -> float | None:
    """Float, or None for missing / 'None' / '-' / NaN / inf (both sources use all of these)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _scaled(value: Any, factor: float) -> float | None:
    number = _num(value)
    return None if number is None else round(number * factor, 6)


# ---------------- yfinance ----------------

def _yfinance_sync(symbol: str) -> dict[str, Any] | None:
    import yfinance as yf

    info = yf.Ticker(symbol).info or {}
    if not (info.get("shortName") or info.get("longName")) or not info.get("sector"):
        return None  # unknown symbol: yfinance returns a near-empty dict
    market_cap = _num(info.get("marketCap"))
    return {
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency"),
        "market_cap": Decimal(str(round(market_cap, 2))) if market_cap is not None else None,
        "pe_ratio": _num(info.get("trailingPE")),
        "forward_pe": _num(info.get("forwardPE")),
        "price_to_book": _num(info.get("priceToBook")),
        "eps": _num(info.get("trailingEps")),
        "roe": _num(info.get("returnOnEquity")),
        "debt_to_equity": _scaled(info.get("debtToEquity"), 0.01),       # % -> ratio
        "dividend_yield_pct": _num(info.get("dividendYield")),           # already a percentage
        "profit_margin": _num(info.get("profitMargins")),
        "revenue_growth": _num(info.get("revenueGrowth")),
        "week52_high": _num(info.get("fiftyTwoWeekHigh")),
        "week52_low": _num(info.get("fiftyTwoWeekLow")),
        "source": "yfinance",
    }


async def fetch_yfinance_fundamentals(symbol: str) -> dict[str, Any] | None:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_yfinance_sync, symbol), timeout=YFINANCE_TIMEOUT)
    except Exception as exc:  # network, Yahoo rate limit, parsing, timeout
        logger.error("[fundamentals] yfinance failed for %s: %s: %s", symbol, type(exc).__name__, exc)
        return None


# ---------------- Alpha Vantage OVERVIEW (fallback) ----------------

def parse_overview(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not payload.get("Symbol"):
        return None  # Alpha Vantage answers {} for symbols it doesn't cover
    market_cap = _num(payload.get("MarketCapitalization"))
    return {
        "name": payload.get("Name"),
        "sector": (payload.get("Sector") or "").title() or None,     # "TECHNOLOGY" -> "Technology"
        "industry": (payload.get("Industry") or "").title() or None,
        "currency": payload.get("Currency"),
        "market_cap": Decimal(str(round(market_cap, 2))) if market_cap is not None else None,
        "pe_ratio": _num(payload.get("TrailingPE")) or _num(payload.get("PERatio")),
        "forward_pe": _num(payload.get("ForwardPE")),
        "price_to_book": _num(payload.get("PriceToBookRatio")),
        "eps": _num(payload.get("EPS")),
        "roe": _num(payload.get("ReturnOnEquityTTM")),
        "debt_to_equity": None,                                       # not in OVERVIEW
        "dividend_yield_pct": _scaled(payload.get("DividendYield"), 100),  # fraction -> %
        "profit_margin": _num(payload.get("ProfitMargin")),
        "revenue_growth": _num(payload.get("QuarterlyRevenueGrowthYOY")),
        "week52_high": _num(payload.get("52WeekHigh")),
        "week52_low": _num(payload.get("52WeekLow")),
        "source": "alphavantage",
    }


async def fetch_alphavantage_overview(symbol: str, client: httpx.AsyncClient | None = None) -> dict[str, Any] | None:
    if not market_data.alphavantage_available(f"OVERVIEW for {symbol}"):
        return None
    params = {"function": "OVERVIEW", "symbol": market_data._alphavantage_symbol(symbol)}
    try:
        async with http_client(client) as http:
            payload = await market_data.alphavantage_query(http, params, symbol)
    except market_data.AlphaVantageRateLimitError as exc:
        market_data.start_alphavantage_cooldown(str(exc))
        return None
    return parse_overview(payload) if payload else None


# ---------------- cache ----------------

def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def get_cached(symbol: str, session_factory: async_sessionmaker[AsyncSession]) -> CompanyFundamentals | None:
    async with session_factory() as db:
        return await db.scalar(select(CompanyFundamentals).where(CompanyFundamentals.symbol == symbol))


async def refresh_if_stale(
    symbol: str,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    client: httpx.AsyncClient | None = None,
) -> CompanyFundamentals | None:
    """
    Return fundamentals for `symbol`, refreshing the cache if it is missing or older
    than a week. If every source fails, an old cached row is still returned (stale is
    better than nothing for slow-moving data); None only if nothing was ever fetched.
    """
    cached = await get_cached(symbol, session_factory)
    if cached is not None and datetime.now(UTC) - _as_utc(cached.fetched_at) < CACHE_MAX_AGE:
        return cached

    data = await fetch_yfinance_fundamentals(symbol) or await fetch_alphavantage_overview(symbol, client)
    if data is None:
        if cached is not None:
            logger.warning("[fundamentals] refresh failed for %s; using data from %s", symbol, cached.fetched_at)
        return cached

    values = {column: data[column] for column in COLUMNS} | {"source": data["source"], "fetched_at": datetime.now(UTC)}
    async with session_factory() as db:
        stmt = pg_insert(CompanyFundamentals).values(symbol=symbol, **values)
        await db.execute(stmt.on_conflict_do_update(index_elements=["symbol"], set_=values))
        await db.commit()
    logger.info("[fundamentals] %s refreshed from %s (P/E %s, sector %s)", symbol, data["source"],
                data["pe_ratio"], data["sector"])
    return await get_cached(symbol, session_factory)
