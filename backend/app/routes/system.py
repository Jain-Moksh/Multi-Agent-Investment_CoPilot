"""
System status page (login required).

GET /system/status   one call with everything the status page shows: database, scheduler
                     jobs (same data as /health/scheduler), table row counts, ChromaDB
                     vector count, LLM keys/models, and which data sources are configured.

Secrets are NEVER returned: only how many keys exist and true/false per data source.
"""

import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import scheduler
from app.core.config import settings
from app.core.database import check_db_connection, get_db
from app.core.dependencies import get_current_user
from app.models import ChatLog, MarketSnapshot, NewsEvent, NewsQuarantine, PriceHistory, Recommendation, User
from app.schemas.system import DatabaseStatus, LLMProviderStatus, LLMStatus, SystemStatus, VectorStoreStatus
from app.services import llm, vector_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])

COUNTED_TABLES = {
    "news_events": NewsEvent, "news_quarantine": NewsQuarantine, "market_snapshots": MarketSnapshot,
    "price_history": PriceHistory, "recommendations": Recommendation, "chat_logs": ChatLog,
}


async def _vector_count() -> VectorStoreStatus:
    try:
        count = await asyncio.to_thread(lambda: vector_store.get_collection().count())
        return VectorStoreStatus(vectors=count, collection=settings.CHROMA_COLLECTION)
    except Exception as exc:  # the status page must render even if Chroma is broken
        logger.warning("[system] could not read ChromaDB: %s", exc)
        return VectorStoreStatus(vectors=None, collection=settings.CHROMA_COLLECTION, error=type(exc).__name__)


def _llm_status() -> LLMStatus:
    primary = settings.LLM_PROVIDER.strip().lower()
    return LLMStatus(
        primary_provider=primary,
        cross_provider_fallback=settings.LLM_CROSS_PROVIDER_FALLBACK,
        providers={name: LLMProviderStatus(keys_configured=len(settings.api_keys(name)), models=llm.models(name))
                   for name in llm.SUPPORTED_PROVIDERS},
    )


@router.get("/status", response_model=SystemStatus)
async def system_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    db_ok, db_error = await check_db_connection()
    counts: dict[str, int | None] = {}
    for name, model in COUNTED_TABLES.items():
        try:
            counts[name] = await db.scalar(select(func.count()).select_from(model))
        except Exception:  # keep the page usable if one count fails
            logger.exception("[system] count failed for %s", name)
            counts[name] = None
    return SystemStatus(
        checked_at=datetime.now(UTC),
        database=DatabaseStatus(ok=db_ok, error=db_error),
        scheduler=scheduler.get_status(),
        row_counts=counts,
        vector_store=await _vector_count(),
        llm=_llm_status(),
        data_sources={
            "gemini": bool(settings.api_keys("gemini")),
            "openai": bool(settings.api_keys("openai")),
            "marketaux": bool(settings.api_keys("marketaux")),
            "alphavantage": bool(settings.api_keys("alphavantage")),
            "zerodha": bool(settings.ZERODHA_API_KEY and settings.ZERODHA_API_SECRET),
        },
    )
