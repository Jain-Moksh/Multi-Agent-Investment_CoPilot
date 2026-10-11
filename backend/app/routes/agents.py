"""
Agent activity log (login required).

GET /agents/logs?limit=50&agent=   recent agent_logs rows, newest first

input_summary / output_summary are stored as JSON text; they are returned parsed.
Privacy: rows whose input names a user_id (Portfolio, User Profiling, Recommendation
agents, the assistant) are only shown to that user; rows about public data (News,
Market, Fundamental agents) are shown to everyone.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models import AgentLog, User
from app.schemas.system import AgentLogOut

router = APIRouter(prefix="/agents", tags=["agents"])

SCAN_WINDOW = 500  # newest rows examined per request (rows of other users are skipped)


def _parse(text: str | None) -> Any:
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


@router.get("/logs", response_model=list[AgentLogOut])
async def agent_logs(
    limit: int = Query(default=50, ge=1, le=200),
    agent: str | None = Query(default=None, max_length=64, description="e.g. news_agent"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AgentLog)
    if agent:
        stmt = stmt.where(AgentLog.agent_name == agent)
    rows = await db.scalars(stmt.order_by(AgentLog.created_at.desc(), AgentLog.id.desc()).limit(SCAN_WINDOW))
    out: list[AgentLogOut] = []
    for row in rows:
        inputs = _parse(row.input_summary)
        owner = inputs.get("user_id") if isinstance(inputs, dict) else None
        if owner is not None and owner != user.id:
            continue
        out.append(AgentLogOut(id=row.id, agent_name=row.agent_name, action=row.action, input_summary=inputs,
                               output_summary=_parse(row.output_summary), created_at=row.created_at))
        if len(out) >= limit:
            break
    return out
