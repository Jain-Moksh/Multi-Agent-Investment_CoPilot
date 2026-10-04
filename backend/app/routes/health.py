"""
Health-check endpoints.

GET /health returns 200 when the API *and* PostgreSQL are reachable,
and 503 (Service Unavailable) when the database cannot be reached.

GET /health/scheduler shows the background jobs: next run times and a
summary of the last run of each (for verifying the scheduler while testing).
It requires login because the watchlist reveals which stocks users hold.
"""

from fastapi import APIRouter, Depends, Response, status

from app.core import scheduler
from app.core.config import settings
from app.core.database import check_db_connection
from app.core.dependencies import get_current_user

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(response: Response) -> dict:
    db_ok, db_error = await check_db_connection()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
        "database": "connected" if db_ok else f"unreachable ({db_error})",
    }


@router.get("/health/scheduler", dependencies=[Depends(get_current_user)])
async def scheduler_status() -> dict:
    return scheduler.get_status()
