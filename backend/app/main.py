"""
FastAPI entry point for the Investment Copilot backend.

Run from the backend/ folder:
    uvicorn app.main:app --reload
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import check_db_connection, engine
from app.core.scheduler import start_scheduler, stop_scheduler
from app.routes import auth, debug, health, portfolio

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s - %(message)s")
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Runs once at startup (before `yield`) and once at shutdown (after)."""
    db_ok, db_error = await check_db_connection()
    if db_ok:
        logger.info("Database connection OK")
    else:
        # Don't crash: the API can still start, and /health will report 503.
        logger.warning("Database unreachable at startup (%s) - check DATABASE_URL in backend/.env", db_error)

    if settings.JWT_SECRET_KEY == "change-me":
        logger.warning("JWT_SECRET_KEY is the insecure default - set a random value in backend/.env")

    start_scheduler()  # background news + market jobs

    yield

    await stop_scheduler()  # stop jobs first: they use the DB engine disposed below
    await engine.dispose()  # close pooled DB connections cleanly


app = FastAPI(
    title=settings.APP_NAME,
    description="Multi-agent, LLM-driven personal investment decision-support API.",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow the React dev server to call the API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers are registered here as features are added.
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(portfolio.router)

# Developer-only tools (no login; localhost only). Never registered outside development.
if settings.is_development:
    app.include_router(debug.router)
