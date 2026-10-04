"""
Market Agent: what do price action and momentum say about one stock?

    result = await MarketAgent().analyze("INFY.NS")

Pure calculation, no LLM. Reads (all through @enforce_permission("market_agent", "read", ...)):
  - market_snapshots      latest intraday price (refreshed every 30 min by the scheduler)
  - price_history         daily closes (~30 days, saved by the same job from yfinance)
  - technical_indicators  cached Alpha Vantage RSI-14, used when fresh

Indicators:
  trend      latest price vs its 7-day moving average of daily closes:
             more than 1% above -> "up", more than 1% below -> "down", else "flat"
  RSI-14     Wilder's Relative Strength Index. Alpha Vantage's value if it is at most
             4 days old, otherwise computed here from the daily closes (needs 15).
             >= 70 "overbought", <= 30 "oversold", else "neutral"

Signal (-1..+1), documented so the panel can follow it:
    signal = 0.7 x trend_part + 0.3 x rsi_part
    trend_part = (% distance from the 7-day average) / 5, capped to -1..+1
    rsi_part   = -1 overbought (likely to cool off), +1 oversold (likely to bounce), 0 neutral
Confidence (0..0.8; technicals alone never give full confidence):
    0.3 base + 0.2 if >= 15 days of history + 0.2 if an RSI is available
    + 0.1 if the latest data is at most 4 days old (covers weekends / holidays)
"""

import logging
import statistics
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.agents.base import BaseAgent, now_iso
from app.models import MarketSnapshot, PriceHistory, TechnicalIndicator
from app.models.enums import AssetType
from app.schemas.portfolio import normalize_symbol
from app.security.permissions import enforce_permission

logger = logging.getLogger(__name__)

AGENT_NAME = "market_agent"
MA_WINDOW = 7
TREND_BAND_PCT = 1.0          # within +-1% of the average = flat
TREND_FULL_SCALE_PCT = 5.0    # 5% away from the average = full-strength trend signal
RSI_PERIOD = 14
RSI_OVERBOUGHT, RSI_OVERSOLD = 70.0, 30.0
RSI_MAX_AGE = timedelta(days=4)
FRESH_DATA_MAX_AGE = timedelta(days=4)
HISTORY_LOOKBACK = 60         # daily bars read from price_history


# ======================================================================
# Pure indicator maths
# ======================================================================

def moving_average(closes: Sequence[float], window: int = MA_WINDOW) -> float | None:
    """Simple average of the last `window` closes; None if there aren't enough."""
    return statistics.fmean(closes[-window:]) if len(closes) >= window else None


def compute_rsi(closes: Sequence[float], period: int = RSI_PERIOD) -> float | None:
    """
    Wilder's RSI on daily closes (oldest first). The first average gain/loss is a
    simple mean of the first `period` changes, then Wilder smoothing:
        avg = (previous_avg x (period - 1) + current) / period
    Needs period + 1 closes. Returns 0..100, or None if there isn't enough data.
    """
    if len(closes) < period + 1:
        return None
    changes = [b - a for a, b in zip(closes, closes[1:], strict=False)]
    gains = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]
    avg_gain = statistics.fmean(gains[:period])
    avg_loss = statistics.fmean(losses[:period])
    for gain, loss in zip(gains[period:], losses[period:], strict=True):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0  # only gains = maximally strong; no movement = neutral
    return round(100 - 100 / (1 + avg_gain / avg_loss), 2)


def classify_trend(pct_vs_ma: float | None) -> str:
    if pct_vs_ma is None or abs(pct_vs_ma) <= TREND_BAND_PCT:
        return "flat"
    return "up" if pct_vs_ma > 0 else "down"


def classify_rsi(rsi: float | None) -> str:
    if rsi is None:
        return "neutral"
    if rsi >= RSI_OVERBOUGHT:
        return "overbought"
    if rsi <= RSI_OVERSOLD:
        return "oversold"
    return "neutral"


def compute_signal(pct_vs_ma: float | None, rsi_signal: str) -> float:
    trend_part = max(-1.0, min(1.0, (pct_vs_ma or 0.0) / TREND_FULL_SCALE_PCT))
    rsi_part = {"overbought": -1.0, "oversold": 1.0}.get(rsi_signal, 0.0)
    return round(0.7 * trend_part + 0.3 * rsi_part, 2)


def compute_confidence(history_days: int, has_rsi: bool, latest_data_age: timedelta | None) -> float:
    score = 0.3
    score += 0.2 if history_days >= RSI_PERIOD + 1 else 0.0
    score += 0.2 if has_rsi else 0.0
    score += 0.1 if latest_data_age is not None and latest_data_age <= FRESH_DATA_MAX_AGE else 0.0
    return round(score, 2)


def build_summary(r: dict[str, Any]) -> str:
    price = f"₹{r['price']:,.2f}"
    if r["status"] == "insufficient_history":
        trend_text = f"{r['symbol']} last traded at {price}; only {r['history_days']} day(s) of history, too few for a trend"
    else:
        direction = "above" if r["pct_vs_ma7"] >= 0 else "below"
        trend_word = {"up": "uptrend", "down": "downtrend", "flat": "no clear trend"}[r["trend"]]
        trend_text = (f"{r['symbol']} at {price} is {abs(r['pct_vs_ma7']):.1f}% {direction} its 7-day average "
                      f"(₹{r['ma7']:,.2f}): {trend_word}")
    if r["rsi"] is None:
        rsi_text = "RSI unavailable"
    else:
        meaning = {"overbought": "overbought, the rise may be stretched",
                   "oversold": "oversold, a rebound is possible",
                   "neutral": "neutral momentum"}[r["rsi_signal"]]
        rsi_text = f"RSI-14 is {r['rsi']:.0f} ({meaning})"
    return f"{trend_text}. {rsi_text}."


# ======================================================================
# The agent
# ======================================================================

class MarketAgent(BaseAgent):
    name = AGENT_NAME

    # ---------------- permission-guarded data access ----------------

    @enforce_permission(AGENT_NAME, "read", "market_snapshots")
    async def _latest_snapshot(self, symbol: str) -> MarketSnapshot | None:
        async with self.session_factory() as db:
            return await db.scalar(
                select(MarketSnapshot).where(MarketSnapshot.symbol == symbol)
                .order_by(MarketSnapshot.fetched_at.desc()).limit(1)
            )

    @enforce_permission(AGENT_NAME, "read", "price_history")
    async def _daily_closes(self, symbol: str) -> list[tuple[date, float]]:
        """(date, close) for the most recent HISTORY_LOOKBACK trading days, oldest first."""
        async with self.session_factory() as db:
            rows = (await db.execute(
                select(PriceHistory.date, PriceHistory.close).where(PriceHistory.symbol == symbol)
                .order_by(PriceHistory.date.desc()).limit(HISTORY_LOOKBACK)
            )).all()
        return [(d, float(c)) for d, c in reversed(rows)]

    @enforce_permission(AGENT_NAME, "read", "technical_indicators")
    async def _cached_rsi(self, symbol: str) -> TechnicalIndicator | None:
        async with self.session_factory() as db:
            return await db.scalar(
                select(TechnicalIndicator).where(TechnicalIndicator.symbol == symbol,
                                                 TechnicalIndicator.indicator == "RSI_14")
            )

    # ---------------- main entry point ----------------

    async def analyze(self, symbol: str) -> dict[str, Any]:
        """Trend + RSI for `symbol`. Every call is logged to agent_logs; errors are logged, then re-raised."""
        symbol = normalize_symbol(AssetType.STOCK, symbol)
        result = self._empty_result(symbol)
        try:
            await self._run(result)
        except Exception as exc:
            result.update(status="error", summary=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            result["rationale"] = result["summary"]
            await self.log_call(
                "analyze",
                {"symbol": symbol},
                {k: result[k] for k in ("status", "trend", "rsi_signal", "rsi", "rsi_source", "price", "ma7",
                                        "pct_vs_ma7", "history_days", "signal", "confidence", "summary")},
            )
        return result

    @staticmethod
    def _empty_result(symbol: str) -> dict[str, Any]:
        return {
            "agent": AGENT_NAME, "symbol": symbol, "status": "ok",
            "trend": "flat", "rsi_signal": "neutral", "summary": "",
            "signal": 0.0, "confidence": 0.0, "rationale": "",
            "price": None, "price_source": None, "price_as_of": None, "change_pct": None,
            "ma7": None, "pct_vs_ma7": None, "rsi": None, "rsi_source": None, "history_days": 0,
            "analyzed_at": now_iso(),
        }

    async def _run(self, result: dict[str, Any]) -> None:
        symbol = result["symbol"]
        snapshot = await self._latest_snapshot(symbol)
        history = await self._daily_closes(symbol)
        closes = [close for _, close in history]
        result["history_days"] = len(closes)

        # Latest price: the intraday snapshot if it is at least as recent as the last daily bar.
        if snapshot is not None and (not history or snapshot.fetched_at.date() >= history[-1][0]):
            result.update(price=float(snapshot.price), price_source="snapshot",
                          price_as_of=snapshot.fetched_at.isoformat(), change_pct=snapshot.change_pct)
            latest_at = snapshot.fetched_at
        elif history:
            last_day, last_close = history[-1]
            result.update(price=last_close, price_source="history", price_as_of=last_day.isoformat())
            latest_at = datetime.combine(last_day, datetime.min.time(), tzinfo=UTC)
        else:
            result.update(status="no_data", summary=f"No market data stored for {symbol} yet.")
            return

        # RSI: fresh Alpha Vantage value if we have one, else computed from our own closes.
        cached = await self._cached_rsi(symbol)
        if cached is not None and date.today() - cached.as_of <= RSI_MAX_AGE:
            result.update(rsi=round(cached.value, 2), rsi_source="alphavantage")
        else:
            rsi = compute_rsi(closes)
            if rsi is not None:
                result.update(rsi=rsi, rsi_source="computed")
        result["rsi_signal"] = classify_rsi(result["rsi"])

        ma7 = moving_average(closes)
        if ma7 is None:
            result["status"] = "insufficient_history"
            result["summary"] = build_summary(result)
            return  # trend unknown: neutral signal, confidence stays 0

        pct = (result["price"] - ma7) / ma7 * 100
        result.update(ma7=round(ma7, 2), pct_vs_ma7=round(pct, 2), trend=classify_trend(pct))
        result["signal"] = compute_signal(pct, result["rsi_signal"])
        result["confidence"] = compute_confidence(len(closes), result["rsi"] is not None,
                                                  datetime.now(UTC) - latest_at)
        result["summary"] = build_summary(result)
