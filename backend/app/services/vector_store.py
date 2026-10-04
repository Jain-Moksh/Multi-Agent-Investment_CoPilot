"""
Vector store for RAG over financial news: local ChromaDB + local embeddings.

    embed_and_store(news_event_id)  check -> embedding -> Chroma (or quarantine)
    embed_many(ids)                 the same, batched (much faster for many rows)
    search_similar(text)            nearest stored articles (for RAG)
    remove_from_store(ids)          take articles back out (e.g. quarantined later)

Rules:
  - Nothing is embedded without passing app/security/rag_poisoning.py first
    (injection verdict must be SAFE; untrusted sources must not form a
    near-duplicate cluster). The check runs inside embed_many(), so a careless
    caller can't bypass it. Failing rows are moved to news_quarantine.
  - The embedding model (all-MiniLM-L6-v2, 384 dimensions) runs locally with
    sentence-transformers, so no LLM/API quota is used. It is loaded ONCE per
    process, on first use (first load downloads ~90 MB, about a minute),
    and reused for every later call.
  - Embeddings are L2-normalised and the collection uses cosine distance
    (0 = same meaning, 1 = unrelated, up to 2 = opposite).
  - Chroma ids are "news-<news_event_id>" and writes are upserts, so
    re-embedding an article replaces it instead of duplicating it.

Model inference and Chroma calls are synchronous, so they run in worker
threads (asyncio.to_thread) to keep FastAPI's event loop responsive.
"""

import asyncio
import logging
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models import NewsEvent

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 384
ENCODE_BATCH_SIZE = 32


# ======================================================================
# Embedding model (loaded once)
# ======================================================================

_model: Any = None
_model_lock = threading.Lock()


def get_embedding_model() -> Any:
    """The shared SentenceTransformer instance; loaded on first call, thread-safe."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:  # another thread may have loaded it while we waited
                from sentence_transformers import SentenceTransformer  # heavy import (torch), only when needed

                logger.info("Loading embedding model %s (first use; may download)", settings.EMBEDDING_MODEL)
                _model = SentenceTransformer(settings.EMBEDDING_MODEL, device="cpu")
    return _model


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Synchronous: texts -> normalised 384-d vectors."""
    vectors = get_embedding_model().encode(
        list(texts), batch_size=ENCODE_BATCH_SIZE, normalize_embeddings=True, show_progress_bar=False
    )
    return [list(map(float, v)) for v in vectors]


# Small LRU cache for texts embedded again and again: the RAG-poisoning check compares
# every new article with the same recent candidates, so without it each scheduler run
# re-embedded hundreds of identical texts. ~5,000 x 384 floats is a few MB.
EMBED_CACHE_SIZE = 5000
_embed_cache: "OrderedDict[str, list[float]]" = OrderedDict()
_embed_cache_lock = threading.Lock()


def embed_texts_cached(texts: Sequence[str]) -> list[list[float]]:
    """Like embed_texts, but reuses vectors for texts seen recently (only new texts hit the model)."""
    with _embed_cache_lock:
        missing = list(dict.fromkeys(t for t in texts if t not in _embed_cache))
    if missing:
        fresh = embed_texts(missing)
        with _embed_cache_lock:
            for text, vector in zip(missing, fresh, strict=True):
                _embed_cache[text] = vector
            while len(_embed_cache) > EMBED_CACHE_SIZE:
                _embed_cache.popitem(last=False)
    with _embed_cache_lock:
        result = []
        for text in texts:
            vector = _embed_cache.get(text)
            if vector is None:  # evicted between the two lock sections (tiny cache): compute directly
                vector = embed_texts([text])[0]
            else:
                _embed_cache.move_to_end(text)
            result.append(vector)
        return result


# ======================================================================
# Chroma
# ======================================================================

@lru_cache
def get_chroma_client() -> Any:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    return chromadb.PersistentClient(
        path=settings.CHROMA_PERSIST_DIR, settings=ChromaSettings(anonymized_telemetry=False)
    )


@lru_cache
def get_collection() -> Any:
    """The "financial_news" collection. We always pass our own embeddings, so Chroma's
    built-in embedding function is disabled (it would download a second model)."""
    return get_chroma_client().get_or_create_collection(
        settings.CHROMA_COLLECTION,
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
        metadata={"description": "Financial news articles that passed the prompt-injection scan"},
    )


def chroma_id(news_event_id: int) -> str:
    return f"news-{news_event_id}"


def news_document(row: NewsEvent) -> str:
    """The text that gets embedded (and stored as the Chroma document)."""
    return f"{row.title}\n{row.description}" if row.description else row.title


def news_metadata(row: NewsEvent) -> dict[str, Any]:
    """
    Chroma metadata. `symbol` is the first affected symbol ("" if none) for simple
    equality filters; `symbols` keeps the full list when there is one.
    """
    metadata: dict[str, Any] = {
        "news_event_id": row.id,
        "symbol": row.affected_symbols[0] if row.affected_symbols else "",
        "source": row.source_api,
        "source_domain": row.source_domain or "",
        "security_status": row.security_status.value,
        "seen_at": int(row.seen_at.timestamp()),  # unix seconds: lets queries filter by recency
    }
    if row.affected_symbols:
        metadata["symbols"] = list(row.affected_symbols)
    return metadata


# ======================================================================
# Public API
# ======================================================================

class EmbedResult(StrEnum):
    EMBEDDED = "embedded"
    QUARANTINED = "quarantined"
    NOT_FOUND = "not_found"


@dataclass
class EmbedReport:
    embedded: list[int] = field(default_factory=list)
    quarantined: list[int] = field(default_factory=list)  # moved to news_quarantine (incl. cluster members)
    not_found: list[int] = field(default_factory=list)


@dataclass
class _Pending:
    news_event_id: int
    embedding: list[float]
    document: str
    metadata: dict[str, Any]


def _upsert(items: list[_Pending]) -> None:
    """Synchronous: write already-embedded, already-approved articles to Chroma."""
    get_collection().upsert(
        ids=[chroma_id(item.news_event_id) for item in items],
        embeddings=[item.embedding for item in items],
        documents=[item.document for item in items],
        metadatas=[item.metadata for item in items],
    )


async def embed_many(
    news_event_ids: Sequence[int], session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal
) -> EmbedReport:
    """
    Run the RAG-poisoning check (app/security/rag_poisoning.py) on each article, then:
      proceed    -> embed + store in Chroma (the check's embedding is reused)
      quarantine -> move the row to news_quarantine; nothing is embedded.
    When a duplicate cluster is found, its other untrusted members still in
    news_events are quarantined too and removed from Chroma.
    """
    from app.security.rag_poisoning import (
        ScanDecision,
        cluster_security_log,
        evaluate_before_embedding,
        move_to_quarantine,
    )

    report = EmbedReport()
    if not news_event_ids:
        return report

    pending: dict[int, _Pending] = {}
    removed_from_store: list[int] = []
    async with session_factory() as db:
        rows = {row.id: row for row in await db.scalars(select(NewsEvent).where(NewsEvent.id.in_(list(news_event_ids))))}

        for news_id in dict.fromkeys(news_event_ids):  # keep order, drop repeats
            row = rows.get(news_id)
            if row is None:
                report.not_found.append(news_id)
                continue
            if news_id in report.quarantined:  # already pulled in as part of an earlier cluster
                continue

            verdict = await evaluate_before_embedding(db, row)
            if verdict.decision == ScanDecision.PROCEED:
                pending[news_id] = _Pending(news_id, verdict.embedding, news_document(row), news_metadata(row))
                continue

            await move_to_quarantine(db, row, verdict.reason)
            report.quarantined.append(news_id)
            if verdict.kind != "duplicate_cluster":
                continue

            db.add(cluster_security_log(row, verdict))
            for member_id in verdict.cluster_news_event_ids:
                member = await db.get(NewsEvent, member_id)
                if member is None:
                    continue
                await move_to_quarantine(
                    db, member, f"member of a duplicate cluster detected with news_event {news_id}: {verdict.reason}"
                )
                report.quarantined.append(member_id)
                pending.pop(member_id, None)          # approved earlier in this batch: undo
                removed_from_store.append(member_id)  # embedded in an earlier run: take it out
        await db.commit()

    if pending:
        await asyncio.to_thread(_upsert, list(pending.values()))
        report.embedded = list(pending)
    if removed_from_store:
        await remove_from_store(removed_from_store)

    logger.info(
        "[vector_store] embedded %d, quarantined %d%s, not found %d",
        len(report.embedded), len(report.quarantined),
        f" (ids {report.quarantined[:10]}{' ...' if len(report.quarantined) > 10 else ''})" if report.quarantined else "",
        len(report.not_found),
    )
    return report


async def embed_and_store(
    news_event_id: int, session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal
) -> EmbedResult:
    """
    Check one news_events row with scan_before_embedding's logic, then either
    embed it into Chroma (metadata {news_event_id, symbol, source,
    security_status, ...}) or move it to news_quarantine.
    """
    report = await embed_many([news_event_id], session_factory)
    if report.embedded:
        return EmbedResult.EMBEDDED
    if news_event_id in report.quarantined:
        return EmbedResult.QUARANTINED
    return EmbedResult.NOT_FOUND


async def remove_from_store(news_event_ids: Sequence[int]) -> None:
    """Delete articles from the vector store (no error if they aren't there)."""
    if news_event_ids:
        await asyncio.to_thread(get_collection().delete, ids=[chroma_id(i) for i in news_event_ids])


async def stored_ids(news_event_ids: Sequence[int]) -> set[int]:
    """Which of these news_event ids are already in the vector store."""
    if not news_event_ids:
        return set()
    result = await asyncio.to_thread(get_collection().get, ids=[chroma_id(i) for i in news_event_ids], include=[])
    return {int(cid.removeprefix("news-")) for cid in result["ids"]}


async def search_similar(
    text: str, n_results: int = 5, where: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """
    Nearest stored articles to `text`, closest first:
    [{"news_event_id", "distance", "document", "metadata"}].
    `where` is a Chroma metadata filter, e.g. {"symbol": "INFY.NS"}.
    """
    collection = get_collection()

    def run() -> dict[str, Any]:
        return collection.query(
            query_embeddings=embed_texts([text]),
            n_results=n_results,
            where=where,
            include=["distances", "documents", "metadatas"],
        )

    result = await asyncio.to_thread(run)
    return [
        {"news_event_id": meta["news_event_id"], "distance": round(dist, 4), "document": doc, "metadata": meta}
        for meta, dist, doc in zip(result["metadatas"][0], result["distances"][0], result["documents"][0], strict=True)
    ]


async def count() -> int:
    return await asyncio.to_thread(get_collection().count)
