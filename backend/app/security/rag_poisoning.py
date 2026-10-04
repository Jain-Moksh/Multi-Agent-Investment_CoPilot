"""
RAG poisoning defence: decide, before an article is embedded into the vector
store, whether it may "proceed" or must be "quarantined".

The threat: anything embedded becomes retrievable context for the agents. An
attacker can publish many near-identical fake stories about one stock on
cheap/unknown sites ("XYZ wins huge government contract!") so that retrieval
for XYZ is dominated by their narrative. Real wire stories are also
republished nearly word-for-word, but by reputable outlets, so similarity
alone isn't evidence; similarity + untrusted sources is.

scan_before_embedding(news_event_id) applies, in order:
  1. Injection scan (Phase 4): the stored scan_content() verdict must be SAFE
     (rows stored before the scanner existed are scanned now). Not SAFE ->
     quarantine.
  2. Source trust: trusted domains -> proceed.
  3. Untrusted source -> duplicate-cluster check against recent articles about
     the same symbol (or, when the article has no symbol, all recent articles)
     from OTHER sites:
       - near-identical (cosine >= 0.95) to a TRUSTED outlet's article
         -> proceed (syndication, e.g. Yahoo Finance republishing Bloomberg);
       - near-identical to articles on 2+ other UNTRUSTED sites
         -> quarantine, and the matching untrusted articles already stored are
            quarantined too (the first copies of a campaign got through
            before the cluster existed).
     These two refinements came from testing on real stored headlines, where
     wire-service syndication produced 0.95+ matches between genuine articles.

Quarantined rows are MOVED from news_events to news_quarantine (no agent may
read that table) and removed from Chroma. Cluster detections are recorded in
security_logs as event_type = rag_poison.
"""

import asyncio
import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Literal
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import AsyncSessionLocal
from app.models import NewsEvent, NewsQuarantine, SecurityLog
from app.models.enums import SecurityEventType, SecurityStatus, Severity

logger = logging.getLogger(__name__)

# ======================================================================
# Source trust
# ======================================================================

# Established financial news outlets, exchanges and regulators. Subdomains are
# trusted too (m.economictimes.indiatimes.com). Extend as needed: unknown
# domains aren't blocked, only checked more strictly (duplicate clusters).
TRUSTED_DOMAINS: frozenset[str] = frozenset({
    # wire services / global financial press
    "reuters.com", "bloomberg.com", "apnews.com", "ft.com", "wsj.com", "cnbc.com",
    # Indian financial and general news
    "economictimes.indiatimes.com", "economictimes.com", "moneycontrol.com", "livemint.com", "business-standard.com",
    "thehindubusinessline.com", "financialexpress.com", "cnbctv18.com", "ndtvprofit.com",
    "businesstoday.in", "thehindu.com", "indianexpress.com", "timesofindia.indiatimes.com",
    "hindustantimes.com", "ndtv.com", "zeebiz.com",
    # exchanges, regulators, official sources
    "nseindia.com", "bseindia.com", "sebi.gov.in", "rbi.org.in", "pib.gov.in", "sec.gov",
})

Trust = Literal["trusted", "untrusted"]


def normalize_domain(domain: str | None) -> str | None:
    """'https://WWW.Reuters.com:443/x' or 'www.reuters.com.' -> 'reuters.com'."""
    if not domain:
        return None
    domain = domain.strip().lower()
    if "://" in domain:
        domain = urlparse(domain).hostname or ""
    domain = domain.split("/")[0].split(":")[0].rstrip(".")
    domain = domain.removeprefix("www.")
    return domain or None


def check_source_trust(domain: str | None) -> Trust:
    """
    "trusted" if `domain` is a TRUSTED_DOMAINS entry or a subdomain of one.
    Look-alikes stay untrusted: "reuters.com.evil.io", "fakereuters.com", "reuters.co".
    """
    host = normalize_domain(domain)
    if host is None:
        return "untrusted"
    if any(host == trusted or host.endswith("." + trusted) for trusted in TRUSTED_DOMAINS):
        return "trusted"
    return "untrusted"


# ======================================================================
# Duplicate clusters
# ======================================================================

SIMILARITY_THRESHOLD = 0.95
CLUSTER_MIN_MATCHES = 2          # "near-identical to MULTIPLE recent articles"
CLUSTER_WINDOW = timedelta(hours=72)
MAX_CLUSTER_CANDIDATES = 200     # per table; keeps the check fast on a busy symbol


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def check_duplicate_cluster(
    new_embedding: Sequence[float],
    existing_embeddings_for_symbol: Iterable[Sequence[float]],
    threshold: float = SIMILARITY_THRESHOLD,
    min_matches: int = CLUSTER_MIN_MATCHES,
) -> bool:
    """
    True if `new_embedding` is near-identical (cosine >= threshold) to at least
    `min_matches` of the given embeddings: recent articles from untrusted
    sources about the same symbol. A sign of coordinated fake content.
    """
    matches = sum(cosine_similarity(new_embedding, e) >= threshold for e in existing_embeddings_for_symbol)
    return matches >= min_matches


# ======================================================================
# The pre-embedding decision
# ======================================================================

class ScanDecision(StrEnum):
    PROCEED = "proceed"
    QUARANTINE = "quarantine"


@dataclass
class PreEmbedVerdict:
    decision: ScanDecision
    reason: str
    kind: Literal["injection", "duplicate_cluster"] | None = None  # why it was quarantined
    trust: Trust | None = None
    embedding: list[float] | None = None                           # reused by the vector store
    max_similarity: float | None = None
    cluster_news_event_ids: list[int] = field(default_factory=list)  # matching rows still in news_events
    cluster_quarantine_ids: list[int] = field(default_factory=list)  # matching rows already quarantined


@dataclass
class _Candidate:
    table: str  # "news_events" | "news_quarantine"
    id: int
    text: str
    domain: str | None
    trust: Trust


async def _ensure_injection_scanned(db: AsyncSession, row: NewsEvent) -> None:
    """Rows stored before the Phase-4 scanner existed get scanned now (result saved on the row)."""
    if row.security_status is not None:
        return
    from app.security.injection_classifier import scan_content

    result = await scan_content(f"{row.title}\n{row.description or ''}")
    row.security_status = SecurityStatus(result["verdict"].lower())
    row.security_reason = result["reason"][:1000]
    await db.flush()


async def _cluster_candidates(db: AsyncSession, row: NewsEvent) -> list[_Candidate]:
    """
    Recent articles about the same symbol(s) (or any recent article, if this one has
    no symbol) from both tables, from OTHER sites: a site repeating its own story
    under two URLs isn't coordination across sources.
    """
    from app.services.vector_store import news_document

    own_domain = normalize_domain(row.source_domain)
    since = row.seen_at - CLUSTER_WINDOW
    candidates: list[_Candidate] = []
    for model, table in ((NewsEvent, "news_events"), (NewsQuarantine, "news_quarantine")):
        stmt = select(model).where(model.seen_at >= since).order_by(model.seen_at.desc()).limit(MAX_CLUSTER_CANDIDATES)
        if model is NewsEvent:
            stmt = stmt.where(NewsEvent.id != row.id)
        if row.affected_symbols:
            stmt = stmt.where(model.affected_symbols.overlap(row.affected_symbols))  # PostgreSQL && on arrays
        for other in await db.scalars(stmt):
            domain = normalize_domain(other.source_domain)
            if own_domain is not None and domain == own_domain:
                continue
            candidates.append(
                _Candidate(table, other.id, news_document(other), domain, check_source_trust(other.source_domain))
            )
    return candidates


async def evaluate_before_embedding(db: AsyncSession, row: NewsEvent) -> PreEmbedVerdict:
    """Full decision with reasons (used by the embedding pipeline). Does not move anything."""
    from app.services.vector_store import embed_texts_cached as embed_texts
    from app.services.vector_store import news_document

    # 1. injection scan
    await _ensure_injection_scanned(db, row)
    if row.security_status != SecurityStatus.SAFE:
        return PreEmbedVerdict(
            ScanDecision.QUARANTINE,
            f"injection scan verdict {row.security_status.value.upper()}: {row.security_reason or 'no reason'}",
            kind="injection",
        )

    # 2. source trust
    trust = check_source_trust(row.source_domain)
    document = news_document(row)
    if trust == "trusted":
        embedding = (await asyncio.to_thread(embed_texts, [document]))[0]
        return PreEmbedVerdict(ScanDecision.PROCEED, f"trusted source ({row.source_domain})", trust=trust, embedding=embedding)

    # 3. untrusted: duplicate-cluster check
    candidates = await _cluster_candidates(db, row)
    vectors = await asyncio.to_thread(embed_texts, [document] + [c.text for c in candidates])
    embedding = vectors[0]
    scored = [(c, v, cosine_similarity(embedding, v)) for c, v in zip(candidates, vectors[1:], strict=True)]
    verdict = PreEmbedVerdict(ScanDecision.PROCEED, "", trust=trust, embedding=embedding,
                              max_similarity=round(max(s for _, _, s in scored), 4) if scored else None)
    source = row.source_domain or "unknown"

    # A copy of a TRUSTED outlet's story is syndication (Yahoo republishing Bloomberg,
    # a mobile mirror of a newspaper), not a fake-news campaign.
    mirrored = [c for c, _, s in scored if c.trust == "trusted" and s >= SIMILARITY_THRESHOLD]
    if mirrored:
        verdict.reason = f"untrusted source ({source}) but republishes a trusted outlet's story ({mirrored[0].domain})"
        return verdict

    # Count matching SITES, not articles: keep each untrusted domain's closest article.
    best_per_domain: dict[str | None, tuple[list[float], float]] = {}
    for c, vector, similarity in scored:
        if c.trust == "untrusted" and similarity > best_per_domain.get(c.domain, ([], -1.0))[1]:
            best_per_domain[c.domain] = (vector, similarity)

    if check_duplicate_cluster(embedding, [vector for vector, _ in best_per_domain.values()]):
        matched = [c for c, _, s in scored if c.trust == "untrusted" and s >= SIMILARITY_THRESHOLD]
        sites = sorted({c.domain or "unknown" for c in matched})
        verdict.decision, verdict.kind = ScanDecision.QUARANTINE, "duplicate_cluster"
        verdict.cluster_news_event_ids = [c.id for c in matched if c.table == "news_events"]
        verdict.cluster_quarantine_ids = [c.id for c in matched if c.table == "news_quarantine"]
        symbols = ", ".join(row.affected_symbols) or "any symbol"
        verdict.reason = (
            f"untrusted source ({source}) and near-identical (cosine >= {SIMILARITY_THRESHOLD}, "
            f"max {verdict.max_similarity}) to {len(matched)} recent article(s) on {len(sites)} other untrusted "
            f"site(s) ({', '.join(sites[:5])}) about {symbols}, with no trusted outlet carrying the story: "
            "possible coordinated fake content"
        )
    else:
        verdict.reason = f"untrusted source ({source}) but no duplicate cluster"
    return verdict


async def scan_before_embedding(
    news_event_id: int, session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal
) -> ScanDecision:
    """
    "proceed" or "quarantine" for one news_events row (see module docstring).
    Read-only apart from saving a first-time injection scan; the vector store's
    embed_many() acts on the decision. A missing row -> "quarantine" (never embed unknowns).
    """
    async with session_factory() as db:
        row = await db.get(NewsEvent, news_event_id)
        if row is None:
            return ScanDecision.QUARANTINE
        verdict = await evaluate_before_embedding(db, row)
        await db.commit()
        return verdict.decision


# ======================================================================
# Moving rows into quarantine
# ======================================================================

async def move_to_quarantine(db: AsyncSession, row: NewsEvent, reason: str) -> NewsQuarantine:
    """Copy `row` into news_quarantine and delete it from news_events (the caller commits)."""
    from app.models.news import NewsColumns

    quarantined = NewsQuarantine(
        original_news_event_id=row.id,
        quarantine_reason=reason[:2000],
        **{name: getattr(row, name) for name in NewsColumns.__annotations__},  # every shared article column
    )
    db.add(quarantined)
    await db.delete(row)
    await db.flush()  # later checks in the same batch must see the move
    logger.warning("[rag_poisoning] quarantined news_event %s (%s): %s", row.id, row.source_domain, reason)
    return quarantined


def cluster_security_log(row: NewsEvent, verdict: PreEmbedVerdict) -> SecurityLog:
    return SecurityLog(
        event_type=SecurityEventType.RAG_POISON,
        severity=Severity.HIGH,
        blocked=True,
        details={
            "origin": "rag_poisoning",
            "kind": verdict.kind,
            "news_event_id": row.id,
            "url": row.url,
            "title": row.title[:300],
            "source_domain": row.source_domain,
            "symbols": list(row.affected_symbols),
            "max_similarity": verdict.max_similarity,
            "cluster_news_event_ids": verdict.cluster_news_event_ids,
            "cluster_quarantine_ids": verdict.cluster_quarantine_ids,
            "reason": verdict.reason,
        },
    )
