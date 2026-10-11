"""
Manual holdings CRUD. Every function takes the current user's id and only
ever touches that user's rows: a holding id belonging to someone else behaves
exactly like a non-existent one (404), so ids can't be probed.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.portfolio_agent import _money
from app.models import MarketSnapshot, PortfolioHolding
from app.models.enums import AssetType, TransactionSource
from app.schemas.portfolio import HoldingCreate, HoldingUpdate


class HoldingNotFound(Exception):
    pass


class HoldingAlreadyExists(Exception):
    pass


class HoldingManagedBySync(Exception):
    """Zerodha-synced rows are overwritten on every sync, so manual edits are refused."""


async def list_holdings(db: AsyncSession, user_id: int) -> Sequence[PortfolioHolding]:
    result = await db.scalars(
        select(PortfolioHolding)
        .where(PortfolioHolding.user_id == user_id)
        .order_by(PortfolioHolding.asset_type, PortfolioHolding.symbol)
    )
    return result.all()


async def _get_owned(db: AsyncSession, user_id: int, holding_id: int) -> PortfolioHolding:
    holding = await db.get(PortfolioHolding, holding_id)
    if holding is None or holding.user_id != user_id:
        raise HoldingNotFound
    return holding


def _ensure_editable(holding: PortfolioHolding) -> None:
    if holding.source == TransactionSource.KITE_SYNC:
        raise HoldingManagedBySync


async def add_holding(db: AsyncSession, user_id: int, data: HoldingCreate) -> PortfolioHolding:
    holding = PortfolioHolding(user_id=user_id, source=TransactionSource.MANUAL, **data.model_dump())
    db.add(holding)
    try:
        await db.commit()
    except IntegrityError as exc:  # same (asset_type, symbol) already entered manually
        await db.rollback()
        raise HoldingAlreadyExists from exc
    await db.refresh(holding)  # load server defaults (added_at)
    return holding


async def update_holding(
    db: AsyncSession, user_id: int, holding_id: int, data: HoldingUpdate
) -> PortfolioHolding:
    holding = await _get_owned(db, user_id, holding_id)
    _ensure_editable(holding)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(holding, field, value)
    await db.commit()
    await db.refresh(holding)
    return holding


async def delete_holding(db: AsyncSession, user_id: int, holding_id: int) -> None:
    holding = await _get_owned(db, user_id, holding_id)
    _ensure_editable(holding)
    await db.delete(holding)
    await db.commit()


# ======================================================================
# Portfolio summary (GET /portfolio/summary)
# ======================================================================

async def latest_snapshots(db: AsyncSession, symbols: list[str]) -> dict[str, MarketSnapshot]:
    """Newest market_snapshots row per symbol (same query shape as PortfolioAgent._snapshot_prices)."""
    if not symbols:
        return {}
    latest = (select(MarketSnapshot.symbol, func.max(MarketSnapshot.fetched_at).label("at"))
              .where(MarketSnapshot.symbol.in_(symbols)).group_by(MarketSnapshot.symbol).subquery())
    rows = await db.scalars(
        select(MarketSnapshot)
        .join(latest, (MarketSnapshot.symbol == latest.c.symbol) & (MarketSnapshot.fetched_at == latest.c.at))
    )
    return {row.symbol: row for row in rows}


def _pct(part: Decimal, whole: Decimal) -> float | None:
    return round(float(part / whole * 100), 2) if whole else None


async def portfolio_summary(db: AsyncSession, user_id: int) -> dict[str, Any]:
    """
    Value every holding the way the Portfolio Agent does: stocks at their latest market
    price, everything else (FD, gold, property, mutual funds: no price feed) and stocks
    without a price at cost, flagged price_missing. Money is rounded like the agent (_money).
    todays_pl: price - previous close, where previous close = price / (1 + change_pct/100).
    """
    holdings = await list_holdings(db, user_id)
    snapshots = await latest_snapshots(db, sorted({h.symbol for h in holdings if h.asset_type == AssetType.STOCK}))

    rows: list[dict[str, Any]] = []
    total_invested = total_value = total_pl = Decimal(0)
    todays_pl: Decimal | None = None
    by_type: dict[AssetType, Decimal] = {}
    for h in holdings:
        snap = snapshots.get(h.symbol) if h.asset_type == AssetType.STOCK else None
        invested = h.quantity * h.avg_buy_price
        value = h.quantity * snap.price if snap else invested
        pl = value - invested if snap else None
        if snap is not None and snap.change_pct is not None and snap.change_pct > -100:
            previous_close = snap.price / (1 + Decimal(str(snap.change_pct)) / 100)
            todays_pl = (todays_pl or Decimal(0)) + h.quantity * (snap.price - previous_close)
        total_invested += invested
        total_value += value
        total_pl += pl or Decimal(0)
        by_type[h.asset_type] = by_type.get(h.asset_type, Decimal(0)) + value
        rows.append({
            "id": h.id, "symbol": h.symbol, "asset_type": h.asset_type, "source": h.source,
            "quantity": float(h.quantity), "avg_buy_price": _money(h.avg_buy_price),
            "current_price": _money(snap.price) if snap else None,
            "price_as_of": snap.fetched_at if snap else None,
            "change_pct": snap.change_pct if snap else None,
            "invested_value": _money(invested), "current_value": _money(value),
            "unrealized_pl": _money(pl), "unrealized_pl_pct": _pct(pl, invested) if pl is not None else None,
            "_value": value, "price_missing": snap is None,
        })

    for row in rows:
        row["weight_pct"] = _pct(row.pop("_value"), total_value)
    return {
        "holdings": rows,
        "totals": {
            "total_invested": _money(total_invested), "total_current_value": _money(total_value),
            "total_pl": _money(total_pl), "total_pl_pct": _pct(total_pl, total_invested),
            "todays_pl": _money(todays_pl),
        },
        "allocation": [{"asset_type": t, "value": _money(v), "percent": _pct(v, total_value)}
                       for t, v in sorted(by_type.items(), key=lambda item: item[1], reverse=True)],
        "priced_holdings": sum(not r["price_missing"] for r in rows),
        "holdings_count": len(rows),
    }
