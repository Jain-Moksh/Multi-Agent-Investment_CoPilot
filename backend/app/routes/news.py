"""
News feed for the frontend (login required).

GET /news?symbol=&sector=&portfolio_only=false&limit=20&offset=0

Only articles with security_status = 'safe' are ever returned: blocked, suspicious,
not-yet-scanned and quarantined articles (those live in news_quarantine) never reach
the UI, the same rule the agents follow. Newest first.
`affects_my_portfolio` is true when one of the article's affected symbols is a stock
the current user holds; portfolio_only=true returns only those articles.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models import NewsEvent, PortfolioHolding, User
from app.models.enums import AssetType, SecurityStatus
from app.schemas.news import NewsItemOut, NewsPage
from app.schemas.portfolio import normalize_symbol

router = APIRouter(prefix="/news", tags=["news"])


async def held_symbols(db: AsyncSession, user_id: int) -> set[str]:
    rows = await db.scalars(
        select(PortfolioHolding.symbol)
        .where(PortfolioHolding.user_id == user_id, PortfolioHolding.asset_type == AssetType.STOCK)
        .distinct()
    )
    return set(rows.all())


@router.get("", response_model=NewsPage)
async def list_news(
    symbol: str | None = Query(default=None, max_length=32, description="e.g. RELIANCE or RELIANCE.NS"),
    sector: str | None = Query(default=None, max_length=64, description="case-insensitive, e.g. Energy"),
    portfolio_only: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    held = await held_symbols(db, user.id)
    conditions = [NewsEvent.security_status == SecurityStatus.SAFE]
    if symbol and symbol.strip():
        conditions.append(NewsEvent.affected_symbols.contains([normalize_symbol(AssetType.STOCK, symbol)]))
    if sector and sector.strip():
        conditions.append(func.lower(NewsEvent.affected_sector) == sector.strip().lower())
    if portfolio_only:
        if not held:
            return NewsPage(items=[], total=0, limit=limit, offset=offset)
        conditions.append(NewsEvent.affected_symbols.overlap(sorted(held)))  # PostgreSQL && on arrays

    total = await db.scalar(select(func.count()).select_from(NewsEvent).where(*conditions))
    rows = await db.scalars(
        select(NewsEvent).where(*conditions)
        .order_by(NewsEvent.seen_at.desc(), NewsEvent.id.desc())
        .limit(limit).offset(offset)
    )
    items = [
        NewsItemOut(
            id=row.id, title=row.title, url=row.url, description=row.description, source_name=row.source_name,
            source_domain=row.source_domain, sentiment=row.sentiment, affected_sector=row.affected_sector,
            affected_symbols=list(row.affected_symbols or []), seen_at=row.seen_at,
            affects_my_portfolio=bool(held.intersection(row.affected_symbols or [])),
        )
        for row in rows
    ]
    return NewsPage(items=items, total=total or 0, limit=limit, offset=offset)
