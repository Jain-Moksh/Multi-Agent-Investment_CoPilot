"""
News ingestion from three free sources:

    GDELT DOC 2.0   - global news index, no key, strict rate limit (keywords batched)
    Google News RSS - India edition, no key
    Marketaux       - per-ticker news with sentiment, free key, ~100 requests/day

Each fetch_* function returns a list of plain dicts and never raises: timeouts,
HTTP errors and malformed responses are logged and produce an empty list, so
one failing source never stops the others.

ingest_news_for_watchlist() runs all sources, scans every NEW article's
title + description for prompt injection (app/security/injection_classifier:
rules first, LLM only for flagged text), and saves it to news_events with
security_status = safe / suspicious / blocked. Agents only read "safe" rows.
Non-safe articles are also recorded in security_logs.
"""

import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models import NewsEvent, NewsQuarantine, SecurityLog
from app.models.enums import SecurityEventType, SecurityStatus, Severity
from app.security.injection_classifier import BLOCKED, SAFE, scan_content
from app.services.http_utils import http_client, safe_get

logger = logging.getLogger(__name__)

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_MAX_RECORDS = 75          # GDELT allows up to 250
# GDELT documents "one request every 5 s" but in practice enforces more strictly,
# and responses can take 20-30 s. These values were tuned against the live API.
GDELT_MIN_INTERVAL = 10.0       # seconds between calls
GDELT_TIMEOUT = 30.0            # seconds
GDELT_RETRIES_ON_429 = 2
GDELT_RETRY_BACKOFF = 15.0      # seconds; doubles on the 2nd retry
GDELT_BATCH_SIZE = 10           # keywords OR-ed into one GDELT query
# GDELT rejects very short search terms ("phrase too short"), and one bad term
# fails the whole OR-batch, so only reasonably plain terms are sent.
GDELT_SAFE_TERM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .'-]{2,}$")

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"

MARKETAUX_URL = "https://api.marketaux.com/v1/news/all"
# Free tier = 100 requests/day, and the scheduler runs every 10 minutes, so calls
# are rationed: at most MARKETAUX_DAILY_BUDGET per UTC day, and each ticker at
# most once per MARKETAUX_SYMBOL_REFRESH. Counters live in memory (reset on restart).
MARKETAUX_DAILY_BUDGET = 90
MARKETAUX_SYMBOL_REFRESH = timedelta(hours=4)

INSERT_CHUNK_SIZE = 500  # rows per INSERT statement

# Watchlist entries like "RELIANCE.NS" / "TCS.BO" are tickers; anything else is free text.
TICKER_PATTERN = re.compile(r"^(?P<base>[A-Z0-9&-]+)\.(NS|BO)$")


def _clean_text(text: str | None) -> str:
    """Collapse runs of whitespace (GDELT titles contain odd spacing)."""
    return re.sub(r"\s+", " ", text or "").strip()


def _domain_of(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url).hostname
    return host.removeprefix("www.") if host else None


# ======================================================================
# GDELT DOC 2.0
# ======================================================================

_gdelt_lock = asyncio.Lock()
_gdelt_last_call = 0.0


async def _wait_for_gdelt_slot() -> None:
    """Space GDELT calls at least GDELT_MIN_INTERVAL seconds apart."""
    global _gdelt_last_call
    async with _gdelt_lock:
        wait = GDELT_MIN_INTERVAL - (time.monotonic() - _gdelt_last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _gdelt_last_call = time.monotonic()


def _parse_gdelt_date(value: str | None) -> datetime | None:
    # Format: "20261001T194500Z"
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC) if value else None
    except ValueError:
        return None


def _gdelt_term(keyword: str) -> str | None:
    """GDELT search term for one keyword: multi-word phrases are quoted; unsafe terms -> None."""
    keyword = keyword.strip()
    if not GDELT_SAFE_TERM.match(keyword):
        return None
    return f'"{keyword}"' if " " in keyword else keyword


def build_gdelt_query(keywords: list[str]) -> str | None:
    """
    ["war", "crude oil"] -> '(war OR "crude oil")'. GDELT requires parentheses
    around OR-ed terms but rejects them around a single term.
    """
    terms: list[str] = []
    for keyword in keywords:
        term = _gdelt_term(keyword)
        if term is None:
            logger.info("[gdelt] skipping keyword %r (too short / unsupported characters)", keyword)
        elif term not in terms:
            terms.append(term)
    if not terms:
        return None
    return terms[0] if len(terms) == 1 else f"({' OR '.join(terms)})"


async def fetch_gdelt(
    keyword: str, timespan: str = "1h", client: httpx.AsyncClient | None = None
) -> list[dict[str, Any]]:
    """
    Recent English-language articles matching `keyword`.
    timespan: GDELT syntax, e.g. "15min", "1h", "1d", "1w".
    Returns [{title, url, seendate (datetime), domain, sourcecountry}].
    """
    return await fetch_gdelt_many([keyword], timespan=timespan, client=client)


async def fetch_gdelt_many(
    keywords: list[str], timespan: str = "1h", client: httpx.AsyncClient | None = None
) -> list[dict[str, Any]]:
    """
    Like fetch_gdelt, but one request for several keywords (OR-ed together).
    GDELT's rate limit is strict, so the scheduler batches keywords this way.
    """
    query = build_gdelt_query(keywords)
    if query is None:
        return []
    keyword = query  # used in log messages below
    params = {
        "query": f"{query} sourcelang:english",
        "mode": "artlist",
        "format": "json",
        "timespan": timespan,
        "maxrecords": GDELT_MAX_RECORDS,
        "sort": "datedesc",
    }

    async with http_client(client) as http:
        response = await safe_get(
            http, "gdelt", GDELT_URL, params,
            timeout=GDELT_TIMEOUT,
            retries_on_429=GDELT_RETRIES_ON_429,
            backoff=GDELT_RETRY_BACKOFF,
            before_attempt=_wait_for_gdelt_slot,
        )
    if response is None:
        return []

    # GDELT reports some errors (bad query, rate limit) as plain text with HTTP 200.
    try:
        payload = response.json()
    except ValueError:
        logger.error("[gdelt] non-JSON response for %r: %s", keyword, response.text[:200])
        return []

    articles = []
    for item in payload.get("articles", []):  # no matches -> {} (no "articles" key)
        if not item.get("url") or not item.get("title"):
            continue
        articles.append(
            {
                "title": _clean_text(item["title"]),
                "url": item["url"],
                "seendate": _parse_gdelt_date(item.get("seendate")),
                "domain": item.get("domain"),
                "sourcecountry": item.get("sourcecountry"),
            }
        )
    logger.info("[gdelt] %r -> %d articles", keyword, len(articles))
    return articles


# ======================================================================
# Google News RSS
# ======================================================================

def _parse_struct_time(value: time.struct_time | None) -> datetime | None:
    return datetime(*value[:6], tzinfo=UTC) if value else None


async def fetch_google_news_rss(
    keyword: str, when: str | None = "1d", client: httpx.AsyncClient | None = None
) -> list[dict[str, Any]]:
    """
    Google News (India, English) search results for `keyword`.
    when: recency filter, e.g. "1h", "1d", "7d" (None = no filter, mixes old articles).
    Returns [{title, link, published (datetime), source, source_url}].
    """
    params = {
        "q": f"{keyword} when:{when}" if when else keyword,
        "hl": "en-IN",
        "gl": "IN",
        "ceid": "IN:en",
    }
    # Fetched with httpx (not feedparser's own downloader) so we control timeouts and errors.
    async with http_client(client) as http:
        response = await safe_get(http, "google_rss", GOOGLE_NEWS_RSS_URL, params)
    if response is None:
        return []

    feed = feedparser.parse(response.text)
    if feed.bozo and not feed.entries:
        logger.error("[google_rss] could not parse feed for %r: %s", keyword, feed.get("bozo_exception"))
        return []

    articles = []
    for entry in feed.entries:
        if not entry.get("link") or not entry.get("title"):
            continue
        source = entry.get("source") or {}
        source_name = source.get("title")
        title = entry["title"]
        # Google appends " - Publisher" to every title; strip it.
        if source_name and title.endswith(f" - {source_name}"):
            title = title[: -len(f" - {source_name}")]
        articles.append(
            {
                "title": _clean_text(title),
                "link": entry["link"],  # a news.google.com redirect URL
                "published": _parse_struct_time(entry.get("published_parsed")),
                "source": source_name,
                "source_url": source.get("href"),
            }
        )
    logger.info("[google_rss] %r -> %d articles", keyword, len(articles))
    return articles


# ======================================================================
# Marketaux
# ======================================================================

class _DailyBudget:
    """Counts requests per UTC day and refuses once the limit is reached."""

    def __init__(self) -> None:
        self.day: date | None = None
        self.used = 0

    def try_spend(self) -> bool:
        today = datetime.now(UTC).date()
        if self.day != today:
            self.day, self.used = today, 0
        if self.used >= MARKETAUX_DAILY_BUDGET:
            return False
        self.used += 1  # counted even if the request then fails: it may still count against the quota
        return True


_marketaux_budget = _DailyBudget()
_marketaux_last_fetch: dict[str, datetime] = {}  # ticker -> when it was last requested


def _marketaux_due(ticker: str) -> bool:
    """True if `ticker` wasn't requested within MARKETAUX_SYMBOL_REFRESH (and records this request)."""
    now = datetime.now(UTC)
    last = _marketaux_last_fetch.get(ticker)
    if last is not None and now - last < MARKETAUX_SYMBOL_REFRESH:
        return False
    _marketaux_last_fetch[ticker] = now
    return True


def _parse_iso_date(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


async def fetch_marketaux(symbol: str, client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    """
    News about one ticker (e.g. "RELIANCE.NS"), with Marketaux's sentiment.
    Returns [{title, url, description, published_at, source, symbols, industry,
    sentiment_score}], where sentiment_score in [-1, 1] is the average of the
    entity scores Marketaux gives for `symbol` within that article.
    """
    if not settings.MARKETAUX_API_KEY:
        logger.warning("[marketaux] MARKETAUX_API_KEY not set - skipping %s", symbol)
        return []
    if not _marketaux_budget.try_spend():
        logger.warning(
            "[marketaux] daily budget of %d requests used up - skipping %s until tomorrow (UTC)",
            MARKETAUX_DAILY_BUDGET, symbol,
        )
        return []

    params = {
        "symbols": symbol,
        "filter_entities": "true",   # only return entities matching `symbols`
        "language": "en",
        "api_token": settings.MARKETAUX_API_KEY,
    }
    async with http_client(client) as http:
        response = await safe_get(http, "marketaux", MARKETAUX_URL, params)
    if response is None:
        return []

    try:
        data = response.json().get("data", [])
    except (ValueError, AttributeError):
        logger.error("[marketaux] unexpected response for %s: %s", symbol, response.text[:200])
        return []

    articles = []
    for item in data:
        if not item.get("url") or not item.get("title"):
            continue
        entities = item.get("entities") or []
        matching = [e for e in entities if e.get("symbol") == symbol] or entities
        scores = [e["sentiment_score"] for e in matching if e.get("sentiment_score") is not None]
        articles.append(
            {
                "title": _clean_text(item["title"]),
                "url": item["url"],
                "description": _clean_text(item.get("description") or item.get("snippet")) or None,
                "published_at": _parse_iso_date(item.get("published_at")),
                "source": item.get("source"),  # a domain, e.g. "economictimes.indiatimes.com"
                "symbols": sorted({e["symbol"] for e in entities if e.get("symbol")}),
                "industry": next((e["industry"] for e in matching if e.get("industry")), None),
                "sentiment_score": round(sum(scores) / len(scores), 4) if scores else None,
            }
        )
    logger.info("[marketaux] %s -> %d articles", symbol, len(articles))
    return articles


# ======================================================================
# Normalisation: source-specific dicts -> news_events rows
# ======================================================================
# Every row has the same keys (required for a multi-row INSERT).

def _row(
    source_api: str,
    url: str,
    title: str,
    seen_at: datetime | None,
    *,
    description: str | None = None,
    source_name: str | None = None,
    source_domain: str | None = None,
    sentiment: float | None = None,
    affected_sector: str | None = None,
    affected_symbols: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "source_api": source_api,
        "url": url,
        "title": title,
        "description": description,
        "source_name": source_name,
        "source_domain": source_domain,
        "sentiment": sentiment,
        "affected_sector": affected_sector,
        "affected_symbols": affected_symbols or [],
        "seen_at": seen_at or datetime.now(UTC),
        "security_status": None,  # filled by _security_scan() before insert
        "security_reason": None,
    }


def _rows_from_gdelt(articles: list[dict]) -> list[dict]:
    return [
        _row("gdelt", a["url"], a["title"], a["seendate"],
             source_name=a["domain"], source_domain=a["domain"])
        for a in articles
    ]


def _rows_from_google(articles: list[dict], ticker: str | None = None) -> list[dict]:
    """`ticker`: the watchlist ticker whose search found these articles; recorded as the
    affected symbol so per-symbol logic (e.g. duplicate-cluster checks) can use it."""
    return [
        _row("google_rss", a["link"], a["title"], a["published"],
             source_name=a["source"], source_domain=_domain_of(a["source_url"]),
             affected_symbols=[ticker] if ticker else None)
        for a in articles
    ]


def _rows_from_marketaux(articles: list[dict]) -> list[dict]:
    return [
        _row("marketaux", a["url"], a["title"], a["published_at"],
             description=a["description"], source_name=a["source"],
             source_domain=_domain_of(a["url"]), sentiment=a["sentiment_score"],
             affected_sector=a["industry"], affected_symbols=a["symbols"])
        for a in articles
    ]


# ======================================================================
# Orchestration
# ======================================================================

@dataclass
class IngestionReport:
    fetched: dict[str, int] = field(default_factory=lambda: {"gdelt": 0, "google_rss": 0, "marketaux": 0})
    inserted: int = 0
    duplicates: int = 0  # already in the DB, or repeated across keywords/sources
    inserted_ids: list[int] = field(default_factory=list)  # news_events ids created by this run
    # Injection-scan verdicts for the NEW articles of this run.
    security: dict[str, int] = field(default_factory=lambda: {"safe": 0, "suspicious": 0, "blocked": 0})


# Optional observer for debugging (used by /debug/trace): called once per source
# call with (source, label, raw result or the exception it raised).
TraceHook = Callable[[str, str, list[dict] | BaseException], None]


def _split_watchlist_item(item: str) -> tuple[str, str | None]:
    """
    "RELIANCE.NS"   -> ("RELIANCE", "RELIANCE.NS")  text search + Marketaux ticker
    "RBI repo rate" -> ("RBI repo rate", None)       text search only
    """
    match = TICKER_PATTERN.match(item.strip())
    if match:
        return match.group("base"), item.strip()
    return item.strip(), None


async def _no_results() -> list[dict]:
    return []


async def ingest_news_for_watchlist(
    keywords: list[str],
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    client: httpx.AsyncClient | None = None,
    gdelt_timespan: str = "1h",
    trace: TraceHook | None = None,
) -> IngestionReport:
    """
    Fetch news for every watchlist entry from all three sources and insert new
    articles into news_events (duplicates by URL are skipped).

    Entries can be tickers ("TCS.NS": all three sources) or free-text topics
    ("RBI repo rate": GDELT + Google only, since Marketaux needs a ticker).
    GDELT keywords are batched GDELT_BATCH_SIZE per request; Marketaux calls are
    rationed (MARKETAUX_DAILY_BUDGET / MARKETAUX_SYMBOL_REFRESH).
    `trace`, if given, receives each source's raw result (see TraceHook).
    """
    report = IngestionReport()
    rows: list[dict] = []

    def collect(source: str, label: str, result: list[dict] | BaseException, converter) -> None:
        if trace is not None:
            trace(source, label, result)
        if isinstance(result, BaseException):  # a bug in one source must not lose the others' results
            logger.error("[%s] unexpected error for %s", source, label, exc_info=result)
            return
        report.fetched[source] += len(result)
        rows.extend(converter(result))

    items = [_split_watchlist_item(item) for item in keywords]
    items = [(text, ticker) for text, ticker in items if text]

    async with http_client(client) as http:
        # GDELT: one OR-query per batch of keywords instead of one call per keyword.
        texts = [text for text, _ in items]
        for start in range(0, len(texts), GDELT_BATCH_SIZE):
            batch = texts[start : start + GDELT_BATCH_SIZE]
            try:
                result = await fetch_gdelt_many(batch, timespan=gdelt_timespan, client=http)
            except Exception as exc:
                result = exc
            collect("gdelt", repr(batch), result, _rows_from_gdelt)

        # Google News per keyword; Marketaux per ticker, when its refresh interval has passed.
        for text, ticker in items:
            if ticker is None:
                marketaux, marketaux_label = _no_results(), "(skipped: not a ticker)"
            elif _marketaux_due(ticker):
                marketaux, marketaux_label = fetch_marketaux(ticker, client=http), repr(ticker)
            else:
                marketaux = _no_results()
                marketaux_label = f"{ticker!r} (skipped: requested less than {MARKETAUX_SYMBOL_REFRESH} ago)"
            google_result, marketaux_result = await asyncio.gather(
                fetch_google_news_rss(text, client=http), marketaux, return_exceptions=True
            )
            collect("google_rss", repr(text), google_result, lambda articles, t=ticker: _rows_from_google(articles, t))
            collect("marketaux", marketaux_label, marketaux_result, _rows_from_marketaux)

    # Drop repeats within this batch (same URL found via two keywords).
    unique_rows = list({row["url"]: row for row in rows}.values())

    if unique_rows:
        async with session_factory() as db:
            # Articles stored by an earlier run were scanned then; skip them so the
            # scheduler doesn't spend LLM calls re-scanning the same news every 10 min.
            known = await _existing_urls(db, [row["url"] for row in unique_rows])
            new_rows = [row for row in unique_rows if row["url"] not in known]

            findings = await _security_scan(new_rows, report)

            # Chunked: PostgreSQL allows at most 32,767 bind parameters per statement.
            for start in range(0, len(new_rows), INSERT_CHUNK_SIZE):
                stmt = (
                    pg_insert(NewsEvent)
                    .values(new_rows[start : start + INSERT_CHUNK_SIZE])
                    .on_conflict_do_nothing(index_elements=["url"])  # stored concurrently meanwhile
                    .returning(NewsEvent.id)
                )
                report.inserted_ids += [row.id for row in (await db.execute(stmt)).all()]
            db.add_all(findings)  # security_logs entries for SUSPICIOUS / BLOCKED articles
            await db.commit()
        report.inserted = len(report.inserted_ids)

    report.duplicates = len(rows) - report.inserted
    logger.info(
        "News ingestion done: fetched %s, inserted %d, duplicates %d, security %s",
        report.fetched, report.inserted, report.duplicates, report.security,
    )
    return report


async def _existing_urls(db: AsyncSession, urls: list[str]) -> set[str]:
    """URLs already stored, either in news_events or in news_quarantine (held back before embedding)."""
    known: set[str] = set()
    for start in range(0, len(urls), 1000):  # keep each IN (...) list well under the parameter limit
        chunk = urls[start : start + 1000]
        for model in (NewsEvent, NewsQuarantine):
            known.update(await db.scalars(select(model.url).where(model.url.in_(chunk))))
    return known


async def _security_scan(rows: list[dict[str, Any]], report: "IngestionReport") -> list[SecurityLog]:
    """
    Run scan_content() on each article's title + description (rules first, LLM only
    when the rules flag something), write the verdict into the row, and return
    security_logs entries for everything that isn't SAFE.
    """
    results = await asyncio.gather(
        *(scan_content(f"{row['title']}\n{row['description'] or ''}") for row in rows)
    )
    findings: list[SecurityLog] = []
    for row, result in zip(rows, results, strict=True):
        verdict = result["verdict"]
        row["security_status"] = SecurityStatus(verdict.lower())
        row["security_reason"] = result["reason"][:1000]
        report.security[verdict.lower()] += 1
        if verdict == SAFE:
            continue
        logger.warning("[security] %s news article from %s: %s | %s", verdict, row["source_api"], row["title"][:100], result["reason"])
        findings.append(
            SecurityLog(
                event_type=SecurityEventType.PROMPT_INJECTION,
                severity=Severity.HIGH if verdict == BLOCKED else Severity.MEDIUM,
                blocked=verdict == BLOCKED,
                details={
                    "origin": "news_ingestion",
                    "source_api": row["source_api"],
                    "url": row["url"],
                    "title": row["title"][:300],
                    "verdict": verdict,
                    "stage": result["stage"],
                    "matched_patterns": result["matched_patterns"],
                    "reason": result["reason"],
                },
            )
        )
    return findings
