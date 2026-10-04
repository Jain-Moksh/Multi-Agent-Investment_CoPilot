"""
Manual holdings CRUD. Every function takes the current user's id and only
ever touches that user's rows: a holding id belonging to someone else behaves
exactly like a non-existent one (404), so ids can't be probed.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PortfolioHolding
from app.models.enums import TransactionSource
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
