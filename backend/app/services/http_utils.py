"""
Shared HTTP helpers for calling external data APIs (news, market data).

safe_get() never raises: timeouts, connection errors and non-200 responses are
logged and turned into None, so one failing source can't crash a pipeline.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# httpx logs every request URL at INFO, which would leak API keys passed as
# query params (Marketaux's api_token, Alpha Vantage's apikey). Only let its
# warnings/errors through.
logging.getLogger("httpx").setLevel(logging.WARNING)

HTTP_TIMEOUT = httpx.Timeout(15.0)
HEADERS = {"User-Agent": "InvestmentCopilot/0.1 (academic project)"}


@asynccontextmanager
async def http_client(client: httpx.AsyncClient | None = None) -> AsyncIterator[httpx.AsyncClient]:
    """Reuse the caller's client if given (connection pooling, tests), else open a temporary one."""
    if client is not None:
        yield client
        return
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=HEADERS, follow_redirects=True) as new_client:
        yield new_client


async def safe_get(
    client: httpx.AsyncClient,
    source: str,
    url: str,
    params: dict[str, Any],
    *,
    timeout: float | None = None,
    retries_on_429: int = 0,
    backoff: float = 0.0,
    before_attempt: Callable[[], Awaitable[None]] | None = None,
) -> httpx.Response | None:
    """
    GET that returns None instead of raising. Never logs the URL or params
    (they may hold API keys).

    retries_on_429 / backoff: on HTTP 429 (rate-limited), wait backoff, 2*backoff, ...
    and try again. before_attempt: awaited before every attempt (used for throttling).
    """
    for attempt in range(retries_on_429 + 1):
        if before_attempt is not None:
            await before_attempt()
        try:
            response = await client.get(url, params=params, timeout=timeout or HTTP_TIMEOUT)
        except httpx.TimeoutException:
            logger.error("[%s] request timed out", source)
            return None
        except httpx.HTTPError as exc:
            logger.error("[%s] request failed: %s", source, type(exc).__name__)
            return None

        if response.status_code == 429 and attempt < retries_on_429:
            delay = backoff * (attempt + 1)
            logger.warning("[%s] rate-limited (HTTP 429), retrying in %.0fs", source, delay)
            await asyncio.sleep(delay)
            continue
        if response.status_code != 200:
            logger.error("[%s] HTTP %s: %s", source, response.status_code, response.text[:200])
            return None
        return response
    return None
