"""
Background jobs (APScheduler, running on FastAPI's own asyncio event loop).

    news_ingestion  every 10 min: macro-shock keywords + every held stock -> news_events
                    (injection-scanned), then RAG-poisoning check -> Chroma or news_quarantine
    market_update   every 30 min: every held stock -> market_snapshots, price_history (+ cached RSI),
                    and company_fundamentals when older than a week

Lifecycle: main.py's lifespan calls start_scheduler() at startup and
stop_scheduler() at shutdown. Each run is logged (start, items processed,
errors, duration) and its summary kept in memory for GET /health/scheduler.

Safety rules for every job:
  - max_instances=1: if a run is still going when the next one is due (e.g.
    GDELT is slow), the new one is skipped instead of piling up.
  - coalesce=True: after the laptop sleeps, missed runs collapse into one.
  - A job never raises into the scheduler; errors are logged and counted.

NOTE: run the API with ONE worker process. Each process starts its own
scheduler, so `--workers 4` would run every job 4 times.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models import PortfolioHolding
from app.models.enums import AssetType

logger = logging.getLogger("app.scheduler")

# Always watched, whatever users hold: events that move the whole market.
MACRO_SHOCK_KEYWORDS = ["war", "recession", "RBI repo rate", "crude oil"]

NEWS_JOB_ID = "news_ingestion"
MARKET_JOB_ID = "market_update"


# ======================================================================
# Job bookkeeping (what /health/scheduler shows)
# ======================================================================

@dataclass
class JobRun:
    started_at: datetime
    finished_at: datetime | None = None
    duration_s: float | None = None
    items: int = 0                       # keywords searched / symbols updated
    succeeded: int = 0
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    status: str = "running"              # running | ok | partial | failed


_last_runs: dict[str, JobRun] = {}
_running_tasks: set[asyncio.Task] = set()   # cancelled on shutdown
_scheduler: AsyncIOScheduler | None = None


def get_status() -> dict[str, Any]:
    """Scheduler state for GET /health/scheduler."""
    jobs = []
    if _scheduler is not None and _scheduler.running:
        for job in _scheduler.get_jobs():
            jobs.append({"id": job.id, "next_run_at": job.next_run_time})
    return {
        "running": bool(_scheduler and _scheduler.running),
        "jobs": jobs,
        "last_runs": {job_id: asdict(run) for job_id, run in _last_runs.items()},
    }


def _logged_job(job_id: str, body: Callable[[JobRun], Awaitable[None]]) -> Callable[[], Awaitable[None]]:
    """Wrap a job: track its task, time it, log start/end, never let it raise."""

    async def run() -> None:
        task = asyncio.current_task()
        if task is not None:
            _running_tasks.add(task)
        record = JobRun(started_at=datetime.now(UTC))
        _last_runs[job_id] = record
        start = time.monotonic()
        logger.info("[%s] run started at %s", job_id, record.started_at.isoformat(timespec="seconds"))
        try:
            await body(record)
            record.status = "ok" if not record.errors else ("partial" if record.succeeded else "failed")
        except asyncio.CancelledError:
            record.status = "failed"
            record.errors.append("cancelled (app shutting down)")
            logger.warning("[%s] cancelled during shutdown", job_id)
            raise
        except Exception as exc:  # e.g. database down: log, don't kill the scheduler
            record.status = "failed"
            record.errors.append(f"{type(exc).__name__}: {exc}")
            logger.exception("[%s] run failed", job_id)
        finally:
            record.finished_at = datetime.now(UTC)
            record.duration_s = round(time.monotonic() - start, 1)
            if task is not None:
                _running_tasks.discard(task)
        logger.info(
            "[%s] run finished: status=%s items=%d succeeded=%d errors=%d duration=%.1fs %s",
            job_id, record.status, record.items, record.succeeded, len(record.errors),
            record.duration_s, record.details or "",
        )
        for error in record.errors:
            logger.warning("[%s]   error: %s", job_id, error)

    return run


# ======================================================================
# Watchlist
# ======================================================================

async def held_stock_symbols(session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal) -> list[str]:
    """
    Every distinct stock symbol held by any user (manual or Zerodha-synced).
    FDs, gold, property and mutual funds are excluded: they have no ticker to
    look up news or prices for.
    """
    async with session_factory() as db:
        result = await db.scalars(
            select(PortfolioHolding.symbol)
            .where(PortfolioHolding.asset_type == AssetType.STOCK)
            .distinct()
            .order_by(PortfolioHolding.symbol)
        )
        return list(result.all())


async def build_news_watchlist(
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
) -> list[str]:
    """Macro-shock keywords first, then held stocks (e.g. "RELIANCE.NS")."""
    return MACRO_SHOCK_KEYWORDS + [s for s in await held_stock_symbols(session_factory) if s not in MACRO_SHOCK_KEYWORDS]


# ======================================================================
# Jobs
# ======================================================================

async def news_job_body(record: JobRun, session_factory=AsyncSessionLocal) -> None:
    from app.services.news_ingestion import ingest_news_for_watchlist  # avoid import cycles at startup

    keywords = await build_news_watchlist(session_factory)
    record.items = len(keywords)
    record.details["keywords"] = keywords
    report = await ingest_news_for_watchlist(keywords, session_factory=session_factory)
    record.succeeded = len(keywords)  # ingestion handles per-source failures internally
    record.details.update(fetched=report.fetched, inserted=report.inserted, duplicates=report.duplicates,
                          security=report.security)
    if sum(report.fetched.values()) == 0:
        record.errors.append("no articles fetched from any source (check network / API logs above)")

    # Pipeline step 2: RAG-poisoning check, then embed (or quarantine) the new articles.
    if report.inserted_ids:
        from app.services.vector_store import embed_many

        try:
            embedded = await embed_many(report.inserted_ids, session_factory=session_factory)
            record.details.update(embedded=len(embedded.embedded), quarantined=len(embedded.quarantined))
        except Exception as exc:  # articles stay in news_events un-embedded; the next run doesn't retry them
            record.errors.append(f"embedding step failed: {type(exc).__name__}: {exc}")
            logger.exception("[news_ingestion] embedding step failed")


async def market_job_body(record: JobRun, session_factory=AsyncSessionLocal) -> None:
    from app.services.market_data import update_market_snapshot

    symbols = await held_stock_symbols(session_factory)
    record.items = len(symbols)
    sources: dict[str, int] = {}
    rsi_count = 0
    for symbol in symbols:  # sequential: gentle on Yahoo / NSE rate limits
        try:
            update = await update_market_snapshot(symbol, session_factory=session_factory)
        except Exception as exc:  # update_market_snapshot shouldn't raise, but one symbol must not stop the rest
            record.errors.append(f"{symbol}: {type(exc).__name__}: {exc}")
            continue
        if update.quote is None:
            record.errors.append(f"{symbol}: no price from yfinance or NSE")
            continue
        record.succeeded += 1
        sources[update.quote.source] = sources.get(update.quote.source, 0) + 1
        rsi_count += update.rsi is not None
    record.details.update(price_sources=sources, with_rsi=rsi_count)

    # Fundamentals change slowly: refresh_if_stale only fetches when the cached row is > 7 days old.
    from app.services.fundamentals import refresh_if_stale

    with_fundamentals = 0
    for symbol in symbols:
        try:
            with_fundamentals += await refresh_if_stale(symbol, session_factory) is not None
        except Exception as exc:
            record.errors.append(f"{symbol} fundamentals: {type(exc).__name__}: {exc}")
    record.details["with_fundamentals"] = with_fundamentals


run_news_job = _logged_job(NEWS_JOB_ID, news_job_body)
run_market_job = _logged_job(MARKET_JOB_ID, market_job_body)


# ======================================================================
# Lifecycle
# ======================================================================

def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(
        timezone="Asia/Kolkata",
        job_defaults={"max_instances": 1, "coalesce": True, "misfire_grace_time": 300},
    )
    # First runs are delayed a little so the app finishes starting (and so that
    # `uvicorn --reload` restarts while editing code don't hammer the APIs).
    first_run = datetime.now(UTC) + timedelta(seconds=settings.SCHEDULER_FIRST_RUN_DELAY_SECONDS)
    scheduler.add_job(
        run_news_job, "interval", id=NEWS_JOB_ID, name=NEWS_JOB_ID,
        minutes=settings.NEWS_INGEST_INTERVAL_MINUTES, next_run_time=first_run,
    )
    scheduler.add_job(
        run_market_job, "interval", id=MARKET_JOB_ID, name=MARKET_JOB_ID,
        minutes=settings.MARKET_UPDATE_INTERVAL_MINUTES, next_run_time=first_run + timedelta(seconds=30),
    )
    return scheduler


def start_scheduler() -> None:
    """Call from inside the running event loop (FastAPI lifespan)."""
    global _scheduler
    if not settings.SCHEDULER_ENABLED:
        logger.info("Scheduler disabled (SCHEDULER_ENABLED=false)")
        return
    _scheduler = create_scheduler()
    _scheduler.start()
    logger.info(
        "Scheduler started: news every %d min, market every %d min, first run in %ds",
        settings.NEWS_INGEST_INTERVAL_MINUTES, settings.MARKET_UPDATE_INTERVAL_MINUTES,
        settings.SCHEDULER_FIRST_RUN_DELAY_SECONDS,
    )


async def stop_scheduler() -> None:
    """Stop scheduling new runs, cancel runs in progress, and wait for them to finish."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    _scheduler = None
    if _running_tasks:
        tasks = list(_running_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
