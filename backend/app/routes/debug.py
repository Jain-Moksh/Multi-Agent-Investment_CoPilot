"""
Developer-only debugging endpoints. NOT part of the product.

GET  /debug/trace      plain HTML page with a keyword box
POST /debug/trace/run  runs ingest_news_for_watchlist([keyword]) and returns a
                       plain-text trace: raw articles per source, the rows
                       written to news_events, and every warning/error logged.

There is no login, so two guards replace it:
  - main.py only registers this router when ENVIRONMENT=development;
  - every request must come from this machine (127.0.0.1 / ::1).
Note that the run is real: it calls the APIs (using Marketaux quota) and
writes to the database.
"""

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import get_session_factory  # shared dependency (tests override it)
from app.models import NewsEvent
from app.services import news_ingestion

PAGE = Path(__file__).resolve().parent.parent / "static" / "debug_trace.html"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
MAX_ARTICLES_SHOWN = 50  # per source call


def require_local_request(request: Request) -> None:
    if request.client is None or request.client.host not in LOCAL_HOSTS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Debug endpoints are only available from localhost")


router = APIRouter(prefix="/debug", tags=["debug"], dependencies=[Depends(require_local_request)])


class _CaptureLogs(logging.Handler):
    """Collects log records from the ingestion code while a trace runs."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _fmt(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return "-" if value in (None, "", []) else str(value)


def _format_article(n: int, article: dict[str, Any]) -> str:
    """One raw article: title on the first line, every other field below it."""
    lines = [f"  {n:>3}. {article.get('title', '')}"]
    for key, value in article.items():
        if key != "title":
            lines.append(f"       {key}: {_fmt(value)}")
    return "\n".join(lines)


@router.get("/trace", include_in_schema=False)
async def trace_page() -> FileResponse:
    return FileResponse(PAGE)


@router.post("/trace/run", response_class=PlainTextResponse)
async def trace_run(
    keyword: str = Query(min_length=1, max_length=100),
    timespan: str = Query(default="1h", pattern=r"^\d+(min|h|d|w)$"),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> str:
    out: list[str] = []
    text_query, ticker = news_ingestion._split_watchlist_item(keyword)
    started = time.monotonic()
    out.append(f"=== TRACE for {keyword!r} at {datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC (GDELT timespan {timespan}) ===")
    out.append(
        f"Interpreted as: text search {text_query!r} (GDELT + Google News)"
        + (f", ticker {ticker!r} (Marketaux)" if ticker else ", no ticker (Marketaux skipped)")
    )

    # ---- step 1: raw articles, captured from inside the real ingestion run ----
    out.append("\n--- STEP 1: raw articles returned by each source ---")

    def on_source_result(source: str, label: str, result: list[dict] | BaseException) -> None:
        if isinstance(result, BaseException):
            out.append(f"\n[{source}] {label} -> CRASHED: {type(result).__name__}: {result}")
            return
        out.append(f"\n[{source}] {label} -> {len(result)} article(s)")
        for n, article in enumerate(result[:MAX_ARTICLES_SHOWN], start=1):
            out.append(_format_article(n, article))
        if len(result) > MAX_ARTICLES_SHOWN:
            out.append(f"  ... and {len(result) - MAX_ARTICLES_SHOWN} more")

    capture = _CaptureLogs()
    # app.services: news_ingestion, http_utils, llm; app.security: injection classifier
    watched = [logging.getLogger("app.services"), logging.getLogger("app.security")]
    previous_levels = [lg.level for lg in watched]
    for lg in watched:
        lg.addHandler(capture)
        lg.setLevel(logging.INFO)
    report = None
    try:
        report = await news_ingestion.ingest_news_for_watchlist(
            [keyword], session_factory=session_factory, gdelt_timespan=timespan, trace=on_source_result
        )
    except Exception as exc:  # e.g. database down: show it instead of a bare 500
        out.append(f"\nINGESTION FAILED: {type(exc).__name__}: {exc}")
    finally:
        for lg, level in zip(watched, previous_levels, strict=True):
            lg.removeHandler(capture)
            lg.setLevel(level)

    # ---- step 2: what was written ----
    out.append("\n--- STEP 2: written to news_events ---")
    if report is None:
        out.append("nothing (ingestion failed, see above)")
    else:
        out.append(
            f"fetched {report.fetched} -> inserted {report.inserted} new row(s), "
            f"{report.duplicates} duplicate(s) skipped (URL already stored, or found twice in this run)"
        )
        if report.inserted_ids:
            async with session_factory() as db:
                rows = (
                    await db.scalars(select(NewsEvent).where(NewsEvent.id.in_(report.inserted_ids)).order_by(NewsEvent.id))
                ).all()
            for row in rows:
                out.append(
                    f"  id={row.id} [{row.source_api}] security_status="
                    f"{row.security_status.value if row.security_status else 'NULL (not scanned yet)'}"
                    f" sentiment={_fmt(row.sentiment)} symbols={_fmt(row.affected_symbols)}"
                    f"\n       {row.title}\n       {row.source_name or '-'} ({row.source_domain or '-'}) | {_fmt(row.seen_at)}"
                    f"\n       {row.url}"
                    f"\n       security_reason: {row.security_reason or '-'}"
                )
            out.append(f"security scan of new articles: {report.security}")

    # ---- step 3: problems ----
    out.append("\n--- STEP 3: errors and warnings ---")
    problems = [r for r in capture.records if r.levelno >= logging.WARNING]
    if not problems:
        out.append("(none)")
    for record in problems:
        out.append(f"{record.levelname} {record.name}: {record.getMessage()}")
    out.append("(note: log lines from other requests or the scheduler running at the same time may appear here)")

    out.append(f"\n=== done in {time.monotonic() - started:.1f}s ===")
    return "\n".join(out)
