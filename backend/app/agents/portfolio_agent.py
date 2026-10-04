"""
Portfolio Agent: how does one stock fit into THIS user's portfolio?

    result = await PortfolioAgent().analyze(user_id=7, symbol="INFY.NS")

Pure calculation, no LLM. Reads (all through @enforce_permission("portfolio_agent", "read", ...),
and every query is filtered to this user_id):
  - portfolio_holdings   the user's positions (manual + Zerodha rows are combined)
  - transactions         the user's trades in this symbol
  - market_snapshots / price_history   current prices (public market data)

Computes:
  - position: quantity, average cost, current price and value
  - unrealised P/L (Rs and %), and realised P/L from the trade history (FIFO)
  - position weight = position value / total portfolio value -> concentration risk
        < 10% low,  10-25% medium,  > 25% high   ("none" if not held)
    Stocks are valued at their latest price; FDs, gold, property and mutual funds
    (no price feed) are valued at cost and counted in `valued_at_cost_assets`.
  - holding period from the oldest open FIFO lot, and the Indian capital-gains term
    a sale would fall under today (> 365 days = long-term)

Signal (-1..+1): from the portfolio's point of view, should the user add more?
    not held / low weight  -> +0.1   (room to add)
    medium (10-25%)        -> -0.2
    high (25-40%)          -> -0.6   (already concentrated: adding increases risk)
    very high (> 40%)      -> -0.9
Confidence (0..1): 1.0 when every stock in the portfolio has a current price; lower
when values had to fall back to cost or prices are older than 4 days.
"""

import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.agents.base import BaseAgent, now_iso
from app.models import MarketSnapshot, PortfolioHolding, PriceHistory, Transaction
from app.models.enums import AssetType, TransactionAction
from app.schemas.portfolio import normalize_symbol
from app.security.permissions import enforce_permission

logger = logging.getLogger(__name__)

AGENT_NAME = "portfolio_agent"
LOW_WEIGHT_PCT, HIGH_WEIGHT_PCT, VERY_HIGH_WEIGHT_PCT = 10.0, 25.0, 40.0
LONG_TERM_DAYS = 365
STALE_PRICE = timedelta(days=4)


@dataclass
class Price:
    value: Decimal
    source: str          # "snapshot" | "history"
    as_of: datetime


# ======================================================================
# Pure calculations
# ======================================================================

@dataclass
class FifoResult:
    realized_pl: Decimal
    open_quantity: Decimal
    oldest_open_date: date | None
    complete: bool       # False if sells exceed the recorded buys (history starts mid-way)


def fifo(transactions: list[Transaction]) -> FifoResult:
    """Match sells against the oldest buys first (FIFO), like Indian tax rules for shares."""
    lots: deque[list] = deque()  # [remaining quantity, price, date]
    realized = Decimal(0)
    complete = True
    for t in sorted(transactions, key=lambda t: t.transaction_date):
        if t.action == TransactionAction.BUY:
            lots.append([t.quantity, t.price, t.transaction_date.date()])
            continue
        to_sell = t.quantity
        while to_sell > 0 and lots:
            lot = lots[0]
            used = min(to_sell, lot[0])
            realized += (t.price - lot[1]) * used
            lot[0] -= used
            to_sell -= used
            if lot[0] == 0:
                lots.popleft()
        if to_sell > 0:  # sold shares bought before the recorded history begins
            complete = False
    return FifoResult(
        realized_pl=realized,
        open_quantity=sum((lot[0] for lot in lots), Decimal(0)),
        oldest_open_date=lots[0][2] if lots else None,
        complete=complete,
    )


def concentration_risk(weight_pct: float | None) -> str:
    if weight_pct is None or weight_pct == 0:
        return "none"
    if weight_pct < LOW_WEIGHT_PCT:
        return "low"
    return "medium" if weight_pct <= HIGH_WEIGHT_PCT else "high"


def compute_signal(weight_pct: float | None) -> float:
    if weight_pct is None or weight_pct < LOW_WEIGHT_PCT:
        return 0.1
    if weight_pct <= HIGH_WEIGHT_PCT:
        return -0.2
    return -0.6 if weight_pct <= VERY_HIGH_WEIGHT_PCT else -0.9


def compute_confidence(priced: int, stocks: int, symbol_price: Price | None, held: bool) -> float:
    """Share of stock holdings with a current price, minus penalties for a missing/stale price on this symbol."""
    coverage = priced / stocks if stocks else 1.0
    score = 0.4 + 0.6 * coverage
    if held and symbol_price is None:
        score -= 0.3
    elif symbol_price is not None and datetime.now(UTC) - symbol_price.as_of > STALE_PRICE:
        score -= 0.1
    return round(max(0.0, min(1.0, score)), 2)


def _money(value: Decimal | None) -> float | None:
    return None if value is None else round(float(value), 2)


def build_summary(r: dict[str, Any]) -> str:
    if r["status"] == "no_portfolio":
        return "The user has no holdings yet, so there is no concentration risk; any purchase would be a new position."
    notes = "".join(f" Note: {n}" for n in r["notes"])
    if not r["held"]:
        realized = f" Past sales of it realised ₹{r['realized_pl']:,.2f}." if r["sells_count"] else ""
        return (f"{r['symbol']} is not in the portfolio (total ₹{r['total_portfolio_value']:,.2f}); "
                f"buying it would add diversification.{realized}{notes}")
    parts = [f"Holds {r['quantity']:g} {r['symbol']} at an average ₹{r['avg_cost']:,.2f}"]
    if r["unrealized_pl"] is not None:
        sign = "+" if r["unrealized_pl"] >= 0 else "-"
        parts.append(f"now ₹{r['current_price']:,.2f}: {sign}₹{abs(r['unrealized_pl']):,.2f} "
                     f"({r['unrealized_pl_pct']:+.1f}%) unrealised")
    else:
        parts.append("no current price available, so P/L is unknown")
    weight = (f"It is {r['position_weight_pct']:.1f}% of the portfolio ({r['concentration_risk']} concentration risk)"
              if r["position_weight_pct"] is not None else "Its share of the portfolio is unknown")
    term = ""
    if r["tax_term"]:
        term = f"; held {r['holding_days']} days, so a sale now would be {r['tax_term'].replace('_', '-')} for tax"
    return f"{'; '.join(parts)}. {weight}{term}.{notes}"


# ======================================================================
# The agent
# ======================================================================

class PortfolioAgent(BaseAgent):
    name = AGENT_NAME

    # ---------------- permission-guarded data access (always filtered by user) ----------------

    @enforce_permission(AGENT_NAME, "read", "portfolio_holdings")
    async def _user_holdings(self, user_id: int) -> list[PortfolioHolding]:
        async with self.session_factory() as db:
            return list(await db.scalars(select(PortfolioHolding).where(PortfolioHolding.user_id == user_id)))

    @enforce_permission(AGENT_NAME, "read", "transactions")
    async def _symbol_transactions(self, user_id: int, symbol: str) -> list[Transaction]:
        async with self.session_factory() as db:
            return list(await db.scalars(
                select(Transaction).where(Transaction.user_id == user_id, Transaction.symbol == symbol)
                .order_by(Transaction.transaction_date)
            ))

    @enforce_permission(AGENT_NAME, "read", "market_snapshots")
    async def _snapshot_prices(self, symbols: list[str]) -> dict[str, Price]:
        """Latest snapshot price per symbol."""
        if not symbols:
            return {}
        latest = (select(MarketSnapshot.symbol, func.max(MarketSnapshot.fetched_at).label("at"))
                  .where(MarketSnapshot.symbol.in_(symbols)).group_by(MarketSnapshot.symbol).subquery())
        async with self.session_factory() as db:
            rows = (await db.execute(
                select(MarketSnapshot.symbol, MarketSnapshot.price, MarketSnapshot.fetched_at)
                .join(latest, (MarketSnapshot.symbol == latest.c.symbol) & (MarketSnapshot.fetched_at == latest.c.at))
            )).all()
        return {s: Price(p, "snapshot", at) for s, p, at in rows}

    @enforce_permission(AGENT_NAME, "read", "price_history")
    async def _last_closes(self, symbols: list[str]) -> dict[str, Price]:
        """Latest daily close per symbol (fallback when there is no snapshot)."""
        if not symbols:
            return {}
        latest = (select(PriceHistory.symbol, func.max(PriceHistory.date).label("d"))
                  .where(PriceHistory.symbol.in_(symbols)).group_by(PriceHistory.symbol).subquery())
        async with self.session_factory() as db:
            rows = (await db.execute(
                select(PriceHistory.symbol, PriceHistory.close, PriceHistory.date)
                .join(latest, (PriceHistory.symbol == latest.c.symbol) & (PriceHistory.date == latest.c.d))
            )).all()
        return {s: Price(c, "history", datetime.combine(d, datetime.min.time(), tzinfo=UTC)) for s, c, d in rows}

    async def _current_prices(self, symbols: list[str]) -> dict[str, Price]:
        snapshots, closes = await self._snapshot_prices(symbols), await self._last_closes(symbols)
        prices = {}
        for symbol in symbols:
            candidates = [p for p in (snapshots.get(symbol), closes.get(symbol)) if p is not None]
            if candidates:
                prices[symbol] = max(candidates, key=lambda p: p.as_of)  # the more recent one
        return prices

    # ---------------- main entry point ----------------

    async def analyze(self, user_id: int, symbol: str) -> dict[str, Any]:
        """Position, P/L and concentration for `symbol` in `user_id`'s portfolio. Every call is logged."""
        symbol = normalize_symbol(AssetType.STOCK, symbol)
        result = self._empty_result(user_id, symbol)
        try:
            await self._run(result)
        except Exception as exc:
            result.update(status="error", summary=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            result["rationale"] = result["summary"]
            await self.log_call(
                "analyze",
                {"user_id": user_id, "symbol": symbol},
                {k: result[k] for k in ("status", "held", "quantity", "unrealized_pl_pct", "realized_pl",
                                        "position_weight_pct", "concentration_risk", "tax_term", "signal",
                                        "confidence", "summary", "notes")},
            )
        return result

    @staticmethod
    def _empty_result(user_id: int, symbol: str) -> dict[str, Any]:
        return {
            "agent": AGENT_NAME, "user_id": user_id, "symbol": symbol, "status": "ok",
            "held": False, "quantity": 0.0, "avg_cost": None,
            "current_price": None, "price_source": None, "price_as_of": None,
            "invested_value": 0.0, "current_value": 0.0,
            "unrealized_pl": None, "unrealized_pl_pct": None, "realized_pl": 0.0,
            "total_portfolio_value": 0.0, "position_weight_pct": None, "concentration_risk": "none",
            "holdings_count": 0, "valued_at_cost_assets": 0,
            "holding_since": None, "holding_days": None, "tax_term": None,
            "transactions_count": 0, "sells_count": 0, "history_complete": True,
            "open_quantity_from_transactions": 0.0,
            "notes": [],  # data-quality caveats, also appended to the summary
            "signal": 0.0, "confidence": 0.0, "summary": "", "rationale": "",
            "analyzed_at": now_iso(),
        }

    async def _run(self, r: dict[str, Any]) -> None:
        symbol, user_id = r["symbol"], r["user_id"]
        holdings = await self._user_holdings(user_id)
        transactions = await self._symbol_transactions(user_id, symbol)
        r["holdings_count"], r["transactions_count"] = len(holdings), len(transactions)

        stock_symbols = sorted({h.symbol for h in holdings if h.asset_type == AssetType.STOCK} | {symbol})
        prices = await self._current_prices(stock_symbols)

        # ---- whole-portfolio value (stocks at market, everything else at cost) ----
        total = Decimal(0)
        priced_stocks = stocks = 0
        for h in holdings:
            price = prices.get(h.symbol) if h.asset_type == AssetType.STOCK else None
            if h.asset_type == AssetType.STOCK:
                stocks += 1
                priced_stocks += price is not None
            if price is None:
                r["valued_at_cost_assets"] += 1
            total += h.quantity * (price.value if price else h.avg_buy_price)
        r["total_portfolio_value"] = _money(total)

        # ---- this symbol: combine manual + Zerodha rows ----
        rows = [h for h in holdings if h.asset_type == AssetType.STOCK and h.symbol == symbol]
        fifo_result = fifo(transactions)
        r["realized_pl"] = _money(fifo_result.realized_pl)
        r["history_complete"] = fifo_result.complete
        r["sells_count"] = sum(t.action == TransactionAction.SELL for t in transactions)
        r["open_quantity_from_transactions"] = float(fifo_result.open_quantity)
        if not fifo_result.complete:
            r["notes"].append("the trade history starts after some shares were bought, so realised P/L is partial.")
        price = prices.get(symbol)
        if price is not None:
            r.update(current_price=_money(price.value), price_source=price.source, price_as_of=price.as_of.isoformat())

        if not holdings:
            r["status"] = "no_portfolio"
        if rows:
            quantity = sum((h.quantity for h in rows), Decimal(0))
            invested = sum((h.quantity * h.avg_buy_price for h in rows), Decimal(0))
            avg_cost = invested / quantity
            value = quantity * price.value if price else invested
            r.update(held=True, quantity=float(quantity), avg_cost=_money(avg_cost),
                     invested_value=_money(invested), current_value=_money(value))
            if price is not None:
                r["unrealized_pl"] = _money(value - invested)
                r["unrealized_pl_pct"] = round(float((value - invested) / invested * 100), 2) if invested else None
            weight = float(value / total * 100) if total else None
            r["position_weight_pct"] = round(weight, 2) if weight is not None else None
            if fifo_result.oldest_open_date is not None:
                days = (date.today() - fifo_result.oldest_open_date).days
                r.update(holding_since=fifo_result.oldest_open_date.isoformat(), holding_days=days,
                         tax_term="long_term" if days > LONG_TERM_DAYS else "short_term")
            if transactions and fifo_result.complete and fifo_result.open_quantity != quantity:
                r["notes"].append(f"holdings show {float(quantity):g} shares but the recorded trades leave "
                                  f"{float(fifo_result.open_quantity):g}; one of them may be out of date.")
        elif holdings:
            r["status"] = "not_held"
            r["position_weight_pct"] = 0.0
        if not rows and fifo_result.open_quantity > 0:
            r["notes"].append(f"the trade history shows {float(fifo_result.open_quantity):g} shares still open, but they are "
                              "not in the holdings (uploaded trades don't update holdings yet).")

        r["concentration_risk"] = concentration_risk(r["position_weight_pct"])
        r["signal"] = compute_signal(r["position_weight_pct"])
        r["confidence"] = compute_confidence(priced_stocks, stocks, price, r["held"])
        r["summary"] = build_summary(r)
