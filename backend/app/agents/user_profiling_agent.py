"""
User Profiling Agent: how much risk does this user take, and how long do they invest for?

    result = await UserProfilingAgent().analyze(user_id=7)

Pure rules, no LLM. Reads (through @enforce_permission("user_profiling_agent", "read", ...),
every query filtered to this user): transactions, portfolio_holdings, user_profiles.
Writes: user_profiles (the effective profile + how it was decided).

1. Behaviour, from the trade history and current holdings
     avg_holding_days    value-weighted average holding time of every FIFO lot:
                         sold lots buy -> sell, still-open lots buy -> today
     trades_per_month    trades / months since the first trade (at least 1 month)
     quick_flip_pct      % of sold quantity that was held under 30 days
     equity_share_pct    stocks' share of the portfolio (at cost; FDs/gold/property = safe)
     max_position_pct    largest single stock's share of the portfolio (at cost)

2. Rules
     horizon:  avg_holding_days > 365 -> long_term, >= 90 -> medium_term, else short_term
     risk score (sum of points):
         trades_per_month > 8 -> +2,  >= 3 -> +1,  < 1 -> -1
         quick_flip_pct > 30%                     -> +1
         equity_share_pct > 80% -> +1,  < 40%     -> -1
         max_position_pct > 40%                   -> +1
       score >= 2 -> aggressive, <= -1 -> conservative, else moderate
     Behaviour is only used with at least MIN_TRADES trades.

3. Combining with what the user stated (user_profiles.stated_*)
     risk:     the MORE CONSERVATIVE of stated and behaviour (advice should never take
               more risk than the user agreed to, or more than they actually take)
     horizon:  the stated horizon wins (it reflects their goals); else behaviour
     neither:  default moderate / medium_term (basis "default")
   The agent never writes the stated_* columns.
"""

import logging
from collections import deque
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.agents.base import BaseAgent, now_iso
from app.models import PortfolioHolding, Transaction, UserProfile
from app.models.enums import AssetType, InvestmentHorizon, RiskAppetite, TransactionAction
from app.security.permissions import enforce_permission

logger = logging.getLogger(__name__)

AGENT_NAME = "user_profiling_agent"
MIN_TRADES = 5
QUICK_FLIP_DAYS = 30
RISK_ORDER = [RiskAppetite.CONSERVATIVE, RiskAppetite.MODERATE, RiskAppetite.AGGRESSIVE]
DEFAULT_RISK, DEFAULT_HORIZON = RiskAppetite.MODERATE, InvestmentHorizon.MEDIUM_TERM


# ======================================================================
# Behaviour metrics (pure)
# ======================================================================

def holding_metrics(transactions: list[Transaction], today: date) -> dict[str, float | None]:
    """FIFO per symbol -> value-weighted average holding days and % of sold quantity flipped quickly."""
    by_symbol: dict[str, list[Transaction]] = {}
    for t in transactions:
        by_symbol.setdefault(t.symbol, []).append(t)

    weighted_days = total_value = Decimal(0)
    sold_qty = quick_qty = Decimal(0)
    for trades in by_symbol.values():
        lots: deque[list] = deque()  # [remaining qty, price, buy date]
        for t in sorted(trades, key=lambda t: t.transaction_date):
            day = t.transaction_date.date()
            if t.action == TransactionAction.BUY:
                lots.append([t.quantity, t.price, day])
                continue
            remaining = t.quantity
            while remaining > 0 and lots:
                lot = lots[0]
                used = min(remaining, lot[0])
                held = (day - lot[2]).days
                weighted_days += held * used * lot[1]
                total_value += used * lot[1]
                sold_qty += used
                quick_qty += used if held < QUICK_FLIP_DAYS else 0
                lot[0] -= used
                remaining -= used
                if lot[0] == 0:
                    lots.popleft()
        for qty, price, bought in lots:  # still open: held until today
            weighted_days += (today - bought).days * qty * price
            total_value += qty * price

    return {
        "avg_holding_days": round(float(weighted_days / total_value), 1) if total_value else None,
        "quick_flip_pct": round(float(quick_qty / sold_qty * 100), 1) if sold_qty else 0.0,
    }


def trades_per_month(transactions: list[Transaction], today: date) -> float:
    if not transactions:
        return 0.0
    first = min(t.transaction_date.date() for t in transactions)
    months = max((today - first).days, 30) / 30
    return round(len(transactions) / months, 2)


def portfolio_mix(holdings: list[PortfolioHolding]) -> dict[str, float | None]:
    """Shares of the portfolio at cost (this agent has no access to market prices)."""
    values: dict[tuple[str, str], Decimal] = {}
    for h in holdings:
        key = (h.asset_type.value, h.symbol)
        values[key] = values.get(key, Decimal(0)) + h.quantity * h.avg_buy_price
    total = sum(values.values(), Decimal(0))
    if not total:
        return {"equity_share_pct": None, "max_position_pct": None, "distinct_stocks": 0}
    stock_values = [v for (asset, _), v in values.items() if asset == AssetType.STOCK.value]
    return {
        "equity_share_pct": round(float(sum(stock_values, Decimal(0)) / total * 100), 1),
        "max_position_pct": round(float(max(stock_values) / total * 100), 1) if stock_values else 0.0,
        "distinct_stocks": len(stock_values),
    }


# ======================================================================
# Rules (pure)
# ======================================================================

def classify_horizon(avg_holding_days: float | None) -> InvestmentHorizon | None:
    if avg_holding_days is None:
        return None
    if avg_holding_days > 365:
        return InvestmentHorizon.LONG_TERM
    return InvestmentHorizon.MEDIUM_TERM if avg_holding_days >= 90 else InvestmentHorizon.SHORT_TERM


def risk_points(m: dict[str, Any]) -> list[tuple[int, str]]:
    """Every rule that fired: (points, plain-English reason)."""
    points: list[tuple[int, str]] = []
    tpm = m["trades_per_month"]
    if tpm > 8:
        points.append((2, f"very frequent trading ({tpm:g} trades/month)"))
    elif tpm >= 3:
        points.append((1, f"frequent trading ({tpm:g} trades/month)"))
    elif tpm < 1:
        points.append((-1, f"infrequent trading ({tpm:g} trades/month)"))
    if m["quick_flip_pct"] > 30:
        points.append((1, f"{m['quick_flip_pct']:g}% of sold shares were held under {QUICK_FLIP_DAYS} days"))
    equity = m["equity_share_pct"]
    if equity is not None and equity > 80:
        points.append((1, f"{equity:g}% of the portfolio is in stocks"))
    elif equity is not None and equity < 40:
        points.append((-1, f"only {equity:g}% of the portfolio is in stocks"))
    if m["max_position_pct"] is not None and m["max_position_pct"] > 40:
        points.append((1, f"one stock is {m['max_position_pct']:g}% of the portfolio"))
    return points


def classify_risk(points: list[tuple[int, str]]) -> RiskAppetite:
    score = sum(p for p, _ in points)
    if score >= 2:
        return RiskAppetite.AGGRESSIVE
    return RiskAppetite.CONSERVATIVE if score <= -1 else RiskAppetite.MODERATE


def more_conservative(a: RiskAppetite, b: RiskAppetite) -> RiskAppetite:
    return min(a, b, key=RISK_ORDER.index)


def combine(stated: Any, behaviour: Any, *, kind: str) -> tuple[Any, str]:
    """Effective value + basis ("stated", "behaviour", "blended", "default")."""
    if stated is None and behaviour is None:
        return (DEFAULT_RISK if kind == "risk" else DEFAULT_HORIZON), "default"
    if behaviour is None:
        return stated, "stated"
    if stated is None:
        return behaviour, "behaviour"
    if kind == "horizon" or stated == behaviour:
        return stated, "stated"
    return more_conservative(stated, behaviour), "blended"


# ======================================================================
# The agent
# ======================================================================

class UserProfilingAgent(BaseAgent):
    name = AGENT_NAME

    # ---------------- permission-guarded data access (always this user only) ----------------

    @enforce_permission(AGENT_NAME, "read", "transactions")
    async def _transactions(self, user_id: int) -> list[Transaction]:
        async with self.session_factory() as db:
            return list(await db.scalars(select(Transaction).where(Transaction.user_id == user_id)))

    @enforce_permission(AGENT_NAME, "read", "portfolio_holdings")
    async def _holdings(self, user_id: int) -> list[PortfolioHolding]:
        async with self.session_factory() as db:
            return list(await db.scalars(select(PortfolioHolding).where(PortfolioHolding.user_id == user_id)))

    @enforce_permission(AGENT_NAME, "read", "user_profiles")
    async def _profile(self, user_id: int) -> UserProfile | None:
        async with self.session_factory() as db:
            return await db.get(UserProfile, user_id)

    @enforce_permission(AGENT_NAME, "write", "user_profiles")
    async def _save_profile(self, user_id: int, values: dict[str, Any]) -> None:
        """Upsert the effective profile. stated_* columns are never in `values`."""
        if any(key.startswith("stated_") for key in values):  # a real check, not `assert` (stripped by python -O)
            raise ValueError("the profiling agent must never overwrite the user's stated preferences")
        async with self.session_factory() as db:
            stmt = pg_insert(UserProfile).values(user_id=user_id, **values)
            await db.execute(stmt.on_conflict_do_update(index_elements=["user_id"], set_=values))
            await db.commit()

    # ---------------- main entry point ----------------

    async def analyze(self, user_id: int) -> dict[str, Any]:
        """Classify, save to user_profiles, return the classification. Every call is logged."""
        result = self._empty_result(user_id)
        try:
            await self._run(result)
        except Exception as exc:
            result.update(status="error", summary=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            result["rationale"] = result["summary"]
            await self.log_call(
                "analyze",
                {"user_id": user_id},
                {k: result[k] for k in ("status", "risk_appetite", "investment_horizon", "basis", "behaviour",
                                        "stated", "confidence", "summary")},
            )
        return result

    @staticmethod
    def _empty_result(user_id: int) -> dict[str, Any]:
        return {
            "agent": AGENT_NAME, "user_id": user_id, "status": "ok",
            "risk_appetite": None, "investment_horizon": None,
            "basis": {}, "behaviour": {}, "stated": {}, "risk_reasons": [],
            # Not a buy/sell view: the profile tells the Recommendation Agent how much risk is acceptable.
            "signal": 0.0, "confidence": 0.0,
            "summary": "", "rationale": "", "analyzed_at": now_iso(),
        }

    async def _run(self, r: dict[str, Any]) -> None:
        user_id = r["user_id"]
        today = datetime.now(UTC).date()
        transactions = await self._transactions(user_id)
        holdings = await self._holdings(user_id)
        profile = await self._profile(user_id)

        metrics: dict[str, Any] = {"transactions_count": len(transactions),
                                   "trades_per_month": trades_per_month(transactions, today)}
        metrics |= holding_metrics(transactions, today)
        metrics |= portfolio_mix(holdings)
        enough = len(transactions) >= MIN_TRADES

        points = risk_points(metrics) if enough else []
        behaviour_risk = classify_risk(points) if enough else None
        behaviour_horizon = classify_horizon(metrics["avg_holding_days"]) if enough else None
        stated_risk = profile.stated_risk_appetite if profile else None
        stated_horizon = profile.stated_investment_horizon if profile else None

        risk, risk_basis = combine(stated_risk, behaviour_risk, kind="risk")
        horizon, horizon_basis = combine(stated_horizon, behaviour_horizon, kind="horizon")

        r.update(
            status="ok" if enough else "insufficient_history",
            risk_appetite=risk.value, investment_horizon=horizon.value,
            basis={"risk": risk_basis, "horizon": horizon_basis},
            behaviour=metrics | {"risk_appetite": behaviour_risk and behaviour_risk.value,
                                 "investment_horizon": behaviour_horizon and behaviour_horizon.value},
            stated={"risk_appetite": stated_risk and stated_risk.value,
                    "investment_horizon": stated_horizon and stated_horizon.value},
            risk_reasons=[reason for _, reason in points],
            confidence=round(min(1.0, len(transactions) / 20) if enough else (0.5 if stated_risk else 0.0), 2),
        )
        r["summary"] = self._summary(r)

        await self._save_profile(user_id, {
            "risk_appetite": risk, "investment_horizon": horizon,
            "profile_basis": r["basis"], "behavior_metrics": r["behaviour"], "classified_at": datetime.now(UTC),
        })

    @staticmethod
    def _summary(r: dict[str, Any]) -> str:
        b, s = r["behaviour"], r["stated"]
        risk, horizon = r["risk_appetite"], r["investment_horizon"].replace("_", "-")
        if r["status"] == "insufficient_history":
            source = "their stated preferences" if r["basis"]["risk"] == "stated" else "defaults"
            return (f"Only {b['transactions_count']} trade(s) on record (need {MIN_TRADES}), so the profile "
                    f"({risk}, {horizon}) comes from {source}.")
        reasons = "; ".join(r["risk_reasons"]) or "no strong risk signals"
        text = (f"Trading behaviour looks {b['risk_appetite']} ({reasons}) with an average holding period of "
                f"{b['avg_holding_days']:g} days ({b['investment_horizon'].replace('_', '-')}).")
        if r["basis"]["risk"] == "blended":
            text += f" The user stated {s['risk_appetite']}, so the more conservative '{risk}' is used."
        if r["basis"]["horizon"] == "stated" and s["investment_horizon"] != b["investment_horizon"]:
            text += f" Their stated {horizon} horizon is kept."
        return f"{text} Effective profile: {risk}, {horizon}."
