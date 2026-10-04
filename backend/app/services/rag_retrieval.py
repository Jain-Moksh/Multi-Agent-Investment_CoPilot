"""
RAG retrieval: find the stored news most relevant to a question.

    retrieve_relevant_news("Why did Infosys fall today?", symbol="INFY.NS")

Used by the News Agent (Phase 6) and the AI Assistant (Phase 8).

How it works:
  1. The query is embedded with the SAME local model used for the articles
     (all-MiniLM-L6-v2), so query and article vectors are comparable.
  2. Chroma's "financial_news" collection returns the nearest articles,
     optionally filtered to one stock (and/or a recency window).
  3. The matching news_events rows are loaded from PostgreSQL (the source of
     truth) and returned in relevance order.

Safety: only rows that still exist in news_events with security_status =
'safe' are returned. If the vector store holds an entry whose row has since
been quarantined, deleted or re-flagged, it is skipped and removed from
Chroma (self-healing), so stale vectors can never leak unsafe text into an
LLM prompt. To still return `top_k` results after skipping, a few extra
candidates are requested from Chroma.

No permission check here: this is a shared service. Agents call it through
their own @enforce_permission(..., "read", "news_events") wrappers.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import AsyncSessionLocal
from app.models import NewsEvent
from app.models.enums import AssetType, SecurityStatus
from app.schemas.portfolio import normalize_symbol
from app.security.rag_poisoning import check_source_trust
from app.services import vector_store

logger = logging.getLogger(__name__)

MAX_TOP_K = 50
EXTRA_CANDIDATES = 5  # asked from Chroma on top of top_k, to cover skipped stale entries


def build_where(symbol: str | None, max_age_days: int | None) -> dict[str, Any] | None:
    """
    Chroma metadata filter. `symbols` is the article's full list of affected
    symbols, so `$contains` also finds articles where the stock isn't the first one.
    """
    conditions: list[dict[str, Any]] = []
    if symbol:
        conditions.append({"symbols": {"$contains": symbol}})
    if max_age_days is not None:
        since = datetime.now(UTC) - timedelta(days=max_age_days)
        conditions.append({"seen_at": {"$gte": int(since.timestamp())}})
    if not conditions:
        return None
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


def _as_dict(row: NewsEvent, distance: float) -> dict[str, Any]:
    return {
        "news_event_id": row.id,
        "title": row.title,
        "description": row.description,
        "url": row.url,
        "source_api": row.source_api,
        "source_name": row.source_name,
        "source_domain": row.source_domain,
        "source_trust": check_source_trust(row.source_domain),
        "seen_at": row.seen_at.isoformat(),
        "sentiment": row.sentiment,
        "affected_symbols": list(row.affected_symbols),
        "affected_sector": row.affected_sector,
        "similarity": round(1 - distance, 4),  # cosine similarity: 1 = same meaning, ~0 = unrelated
    }


def _title_key(title: str) -> str:
    """Titles compared case/punctuation-insensitively, to spot the same story twice."""
    return " ".join("".join(ch for ch in title.lower() if ch.isalnum() or ch.isspace()).split())


async def _search(
    query: str, where: dict[str, Any] | None, n_results: int, session_factory: async_sessionmaker[AsyncSession]
) -> list[tuple[NewsEvent, float]]:
    """Chroma search + PostgreSQL join; only rows still SAFE. Stale vectors are removed."""
    hits = await vector_store.search_similar(query, n_results=n_results, where=where)
    if not hits:
        return []
    ids = [hit["news_event_id"] for hit in hits]
    async with session_factory() as db:
        rows = {
            row.id: row
            for row in await db.scalars(
                select(NewsEvent).where(NewsEvent.id.in_(ids), NewsEvent.security_status == SecurityStatus.SAFE)
            )
        }
    stale = [news_id for news_id in ids if news_id not in rows]
    if stale:
        logger.warning("[rag] removing %d stale vector(s) whose news row is gone or no longer safe: %s", len(stale), stale)
        await vector_store.remove_from_store(stale)
    return [(rows[hit["news_event_id"]], hit["distance"]) for hit in hits if hit["news_event_id"] in rows]


async def retrieve_relevant_news(
    query: str,
    symbol: str | None = None,
    top_k: int = 5,
    *,
    max_age_days: int | None = None,
    min_similarity: float | None = None,
    symbol_fallback: bool = True,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
) -> list[dict[str, Any]]:
    """
    The `top_k` stored news articles most relevant to `query`, most relevant first.

    symbol:          prefer articles tagged with this stock ("INFY.NS"; "infy" -> "INFY.NS")
    symbol_fallback: many articles carry no symbol tag (GDELT, macro keywords), so if
                     the tagged search finds fewer than top_k, the rest are filled by
                     plain semantic search on the query. Each result says whether it
                     matched the symbol tag (`symbol_match`). False = tagged only.
    max_age_days:    only articles seen in the last N days
    min_similarity:  drop weak matches (e.g. 0.3) instead of always returning top_k

    The same story appearing twice (syndicated copies, one site under two URLs) is
    returned once, preferring the copy from a trusted source.

    Each result: news_event_id, title, description, url, source_api, source_name,
    source_domain, source_trust, seen_at (ISO), sentiment, affected_symbols,
    affected_sector, similarity, symbol_match.
    """
    query = (query or "").strip()
    if not query:
        return []
    top_k = max(1, min(top_k, MAX_TOP_K))
    if symbol:
        symbol = normalize_symbol(AssetType.STOCK, symbol)
    n_results = top_k + EXTRA_CANDIDATES

    candidates = [(row, d, bool(symbol)) for row, d in await _search(query, build_where(symbol, max_age_days),
                                                                     n_results, session_factory)]
    if symbol and symbol_fallback and len(candidates) < top_k:
        seen = {row.id for row, _, _ in candidates}
        for row, distance in await _search(query, build_where(None, max_age_days), n_results, session_factory):
            if row.id not in seen:
                candidates.append((row, distance, symbol in row.affected_symbols))

    results: list[dict[str, Any]] = []
    by_title: dict[str, int] = {}  # title key -> index in results
    for row, distance, symbol_match in candidates:  # tagged matches first, each group in relevance order
        if min_similarity is not None and 1 - distance < min_similarity:
            continue
        item = _as_dict(row, distance) | {"symbol_match": symbol_match}
        key = _title_key(row.title)
        if key in by_title:
            existing = results[by_title[key]]
            if existing["source_trust"] == "untrusted" and item["source_trust"] == "trusted":
                results[by_title[key]] = item  # keep the trusted copy of the same story
            continue
        if len(results) < top_k:
            by_title[key] = len(results)
            results.append(item)

    logger.info("[rag] %r (symbol=%s) -> %d result(s)", query[:80], symbol, len(results))
    return results
