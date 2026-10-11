"""
Recommendation endpoints (login required; users only ever see their own).

POST /recommendations/{symbol}   run the full multi-agent analysis now and save the result
GET  /recommendations            the user's recent recommendations (optionally for one symbol)

A POST is expensive (five agents, market/news lookups, one or two LLM calls), so the
same user can request the same symbol at most once per COOLDOWN; a repeat inside that
window gets 429 with Retry-After. A well-formed symbol for which no price exists at all
(e.g. "ZZNODATA") gets 404 and no recommendation is stored.
"""

import logging
import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.orchestrator import UnknownSymbolError
from app.agents.recommendation_agent import DISCLAIMER, RecommendationAgent, confidence_word
from app.core.database import get_db, get_session_factory
from app.core.dependencies import get_current_user
from app.models import CompanyFundamentals, Recommendation, User
from app.models.enums import AssetType
from app.schemas.portfolio import normalize_symbol
from app.schemas.recommendation import RecommendationOut, RecommendationSummary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

COOLDOWN = timedelta(seconds=30)
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9&-]{1,20}(\.(NS|BO|ns|bo))?$")


def _validated_symbol(symbol: str) -> str:
    if not SYMBOL_PATTERN.match(symbol):
        raise HTTPException(422, "Symbol must look like an NSE/BSE ticker, e.g. INFY, INFY.NS or TCS.BO")
    return normalize_symbol(AssetType.STOCK, symbol)


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@router.post("/{symbol}", response_model=RecommendationOut, status_code=status.HTTP_201_CREATED)
async def create_recommendation(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
):
    """
    Analyse `symbol` for the logged-in user with all five agents and return a Buy / Hold /
    Sell (or Avoid) decision, its confidence, a plain-English explanation and the evidence.
    """
    symbol = _validated_symbol(symbol)
    latest = await db.scalar(
        select(Recommendation.created_at)
        .where(Recommendation.user_id == user.id, Recommendation.symbol == symbol)
        .order_by(Recommendation.created_at.desc()).limit(1)
    )
    if latest is not None:
        wait = COOLDOWN - (datetime.now(UTC) - _as_utc(latest))
        if wait.total_seconds() > 0:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"A recommendation for {symbol} was just generated; try again in {int(wait.total_seconds()) + 1} s.",
                headers={"Retry-After": str(int(wait.total_seconds()) + 1)},
            )
    try:
        return await RecommendationAgent(session_factory).generate(user.id, symbol)
    except UnknownSymbolError as exc:  # no price anywhere: not a real ticker -> nothing is saved
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None


@router.get("/{recommendation_id}", response_model=RecommendationOut)
async def get_recommendation(
    recommendation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rec = await db.get(Recommendation, recommendation_id)
    if rec is None or rec.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recommendation not found")
    details = rec.details or {}
    agreement = details.get("agreement") or {}
    company_name = await db.scalar(select(CompanyFundamentals.name).where(CompanyFundamentals.symbol == rec.symbol))
    return RecommendationOut(
        id=rec.id, symbol=rec.symbol, company_name=company_name, decision=rec.decision.value,
        decision_label=details.get("decision_label") or rec.decision.value.capitalize(),
        confidence=rec.confidence_score, confidence_level=confidence_word(rec.confidence_score),
        overall_lean=rec.overall_lean or 0.0, explanation=rec.explanation,
        explanation_source=details.get("explanation_source") or "unknown", main_driver=details.get("driver"),
        conflicts=agreement.get("conflicts") or [], agents=details.get("agents") or {},
        excluded=agreement.get("excluded") or {}, created_at=rec.created_at, disclaimer=DISCLAIMER,
        details=details or None,
    )


@router.get("", response_model=list[RecommendationSummary])
async def list_recommendations(
    symbol: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Recommendation).where(Recommendation.user_id == user.id)
    if symbol:
        stmt = stmt.where(Recommendation.symbol == _validated_symbol(symbol))
    rows = await db.scalars(stmt.order_by(Recommendation.created_at.desc()).limit(limit))
    return [
        RecommendationSummary(
            id=r.id, symbol=r.symbol, decision=r.decision.value,
            decision_label=(r.details or {}).get("decision_label") or r.decision.value.capitalize(),
            confidence=r.confidence_score, overall_lean=r.overall_lean, explanation=r.explanation,
            created_at=r.created_at,
        )
        for r in rows
    ]
