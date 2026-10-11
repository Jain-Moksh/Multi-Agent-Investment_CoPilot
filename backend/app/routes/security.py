"""
Security dashboard endpoints (login required).

GET  /security/events?type=&limit=50   security_logs, newest first
GET  /security/quarantine?limit=50     news_quarantine rows with the reason
GET  /security/stats                   counts for the dashboard tiles
GET  /security/permissions             the agent allow-list (AGENT_PERMISSIONS)
POST /security/scan-text {text}        run the injection scanner on any text (demo box)

Privacy: chat-related security events carry the user's message, so events that belong
to ANOTHER user (details.user_id) are not returned; system events (news ingestion,
agent permission blocks, RAG poisoning) have no user and are visible to everyone.
scan-text stores nothing: no chat message, no security_logs row, the text is not logged.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models import NewsEvent, NewsQuarantine, SecurityLog, User
from app.models.enums import SecurityEventType, SecurityStatus
from app.schemas.security import QuarantineItemOut, ScanTextIn, ScanTextOut, SecurityEventOut, SecurityStats
from app.security.injection_classifier import scan_content
from app.security.permissions import AGENT_PERMISSIONS

router = APIRouter(prefix="/security", tags=["security"])


def _visible_to(user: User):
    """Events with no user_id (system events) or this user's own."""
    owner = SecurityLog.details["user_id"].astext
    return or_(owner.is_(None), owner == str(user.id))


@router.get("/events", response_model=list[SecurityEventOut])
async def security_events(
    type: SecurityEventType | None = Query(default=None, description="prompt_injection | agent_hijack | rag_poison"),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(SecurityLog).where(_visible_to(user))
    if type is not None:
        stmt = stmt.where(SecurityLog.event_type == type)
    rows = await db.scalars(stmt.order_by(SecurityLog.created_at.desc(), SecurityLog.id.desc()).limit(limit))
    return [SecurityEventOut(id=r.id, event_type=r.event_type.value, severity=r.severity.value, blocked=r.blocked,
                             details=r.details or {}, created_at=r.created_at) for r in rows]


@router.get("/quarantine", response_model=list[QuarantineItemOut])
async def quarantine(
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.scalars(
        select(NewsQuarantine).order_by(NewsQuarantine.quarantined_at.desc(), NewsQuarantine.id.desc()).limit(limit)
    )
    return [
        QuarantineItemOut(
            id=r.id, original_news_event_id=r.original_news_event_id, title=r.title, url=r.url,
            description=r.description, source_api=r.source_api, source_name=r.source_name,
            source_domain=r.source_domain, affected_symbols=list(r.affected_symbols or []),
            security_status=r.security_status.value if r.security_status else None,
            quarantine_reason=r.quarantine_reason, seen_at=r.seen_at, quarantined_at=r.quarantined_at,
        )
        for r in rows
    ]


@router.get("/stats", response_model=SecurityStats)
async def security_stats(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Counts only (no content), over all security events."""
    by_type = {t.value: 0 for t in SecurityEventType}
    for event_type, count in (await db.execute(
        select(SecurityLog.event_type, func.count()).group_by(SecurityLog.event_type)
    )).all():
        by_type[event_type.value] = count
    blocked = await db.scalar(select(func.count()).select_from(SecurityLog).where(SecurityLog.blocked.is_(True)))
    quarantined = await db.scalar(select(func.count()).select_from(NewsQuarantine))
    safe_news = await db.scalar(
        select(func.count()).select_from(NewsEvent).where(NewsEvent.security_status == SecurityStatus.SAFE)
    )
    return SecurityStats(events_total=sum(by_type.values()), events_by_type=by_type, blocked_count=blocked or 0,
                         quarantine_count=quarantined or 0, safe_news_count=safe_news or 0)


@router.get("/permissions", response_model=dict[str, dict[str, list[str]]])
async def permissions(user: User = Depends(get_current_user)):
    """{agent: {"read": [tables], "write": [tables]}}, exactly what @enforce_permission checks."""
    return {agent: {op: sorted(tables) for op, tables in ops.items()} for agent, ops in AGENT_PERMISSIONS.items()}


@router.post("/scan-text", response_model=ScanTextOut)
async def scan_text(body: ScanTextIn, user: User = Depends(get_current_user)):
    """
    Run the Phase-4 injection scanner (rules, then the LLM classifier only if a rule
    matches) on the given text. Max 2000 characters, 10 calls per minute per user.
    Nothing is stored.
    """
    key = str(user.id)
    if wait := rate_limit.SCAN_TEXT_PER_USER.retry_after(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Too many scans; try again in {wait} s.",
                            headers={"Retry-After": str(wait)})
    rate_limit.SCAN_TEXT_PER_USER.hit(key)
    result = await scan_content(body.text)
    return ScanTextOut(verdict=result["verdict"], stage=result["stage"],
                       matched_patterns=result["matched_patterns"], reason=result["reason"])
