"""
Ordered API-key fallback, shared by the LLM client, Marketaux and Alpha Vantage.

A service can have several keys (settings.api_keys). Callers try them IN ORDER and move
to the next key when one fails. How long a failed key is skipped ("rests") depends on why
it failed:
- RATE_LIMIT (per-minute limit, HTTP 429): 60 s, doubling on each repeat, up to 1 h
- QUOTA (daily quota / credits used up, HTTP 402): 6 h
- AUTH (invalid / unauthorised key, HTTP 401/403): 6 h
- OTHER (timeout, server error, bad request): no rest, just try the next key
A success clears the key's record. State lives in memory (resets on restart), which is
enough for a single server process. Keys are only ever logged masked (last 4 chars).

Scope: providers like Gemini count quota per (key, model), so a key that is out of quota
for one model may still work for another. Callers pass `scope` (the model name):
RATE_LIMIT / QUOTA rests only that (key, scope); AUTH (a bad key) rests the key for every
scope. Without `scope` (Marketaux, Alpha Vantage) a rest applies to the whole key.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from app.core.config import settings

logger = logging.getLogger(__name__)

RATE_LIMIT_REST = timedelta(seconds=60)
RATE_LIMIT_MAX_REST = timedelta(hours=1)
LONG_REST = timedelta(hours=6)


class Failure(StrEnum):
    RATE_LIMIT = "rate_limit"
    QUOTA = "quota"
    AUTH = "auth"
    OTHER = "other"


@dataclass
class _KeyState:
    resting_until: datetime
    strikes: int = 0


ALL_SCOPES = ""  # a rest stored under this scope applies to every scope of the key
_state: dict[tuple[str, str, str], _KeyState] = {}  # (service, key, scope) -> rest

_AUTH_HINTS = ("api key not valid", "api_key_invalid", "invalid api key", "incorrect api key", "invalid_api_key",
               "invalid_api_token", "invalid authentication", "permission denied")
# Gemini's 429 text always mentions "plan and billing", so per-minute limits are checked first.
_PER_MINUTE_HINTS = ("per minute", "perminute", "per second", "call frequency")
_QUOTA_HINTS = ("insufficient_quota", "credit", "per day", "perday", "usage_limit", "daily")
_RATE_HINTS = ("resource_exhausted", "rate limit", "rate_limit", "too many requests", "quota", "call frequency")


def mask(key: str) -> str:
    return f"...{key[-4:]}" if len(key) >= 8 else "..."


def classify(status: int | None, message: str) -> Failure:
    """Why did a call fail? `status` is the HTTP status if known, `message` the error text."""
    text = message.lower()
    if status in (401, 403) or any(hint in text for hint in _AUTH_HINTS):
        return Failure.AUTH
    if status == 402:
        return Failure.QUOTA
    if status == 429 or any(hint in text for hint in _RATE_HINTS):
        if any(hint in text for hint in _PER_MINUTE_HINTS):
            return Failure.RATE_LIMIT
        return Failure.QUOTA if any(hint in text for hint in _QUOTA_HINTS) else Failure.RATE_LIMIT
    return Failure.OTHER


def _resting(service: str, key: str, scope: str, now: datetime) -> bool:
    for s in {ALL_SCOPES, scope}:
        state = _state.get((service, key, s))
        if state is not None and now < state.resting_until:
            return True
    return False


def usable_keys(service: str, scope: str | None = None) -> list[str]:
    """The service's keys in their configured order, minus the ones resting for `scope` (or for all scopes)."""
    now = datetime.now(UTC)
    return [key for key in settings.api_keys(service) if not _resting(service, key, scope or ALL_SCOPES, now)]


def next_free_at(service: str) -> datetime | None:
    """When the first resting key of `service` becomes usable again (None if none is resting)."""
    times = [s.resting_until for (svc, _, _), s in _state.items() if svc == service]
    return min(times) if times else None


def report_success(service: str, key: str, scope: str | None = None) -> None:
    _state.pop((service, key, scope or ALL_SCOPES), None)


def report_failure(service: str, key: str, kind: Failure, detail: str = "", scope: str | None = None) -> None:
    position = _position(service, key)
    where = f" for {scope}" if scope and kind is not Failure.AUTH else ""
    if kind is Failure.OTHER:
        logger.warning("[%s] key %s %s failed%s (%s); trying the next option", service, position, mask(key), where,
                       detail[:200])
        return
    # A bad key is bad for every model; a rate limit / quota only for the model that hit it.
    slot = (service, key, ALL_SCOPES if kind is Failure.AUTH else (scope or ALL_SCOPES))
    now = datetime.now(UTC)
    state = _state.get(slot)
    strikes = (state.strikes if state else 0) + 1
    if kind is Failure.RATE_LIMIT:
        rest = min(RATE_LIMIT_REST * 2 ** (strikes - 1), RATE_LIMIT_MAX_REST)
    else:
        rest = LONG_REST
    _state[slot] = _KeyState(resting_until=now + rest, strikes=strikes)
    logger.warning("[%s] key %s %s: %s%s - skipping it for %s and using the next option. %s",
                   service, position, mask(key), kind.value, where, rest, detail[:200])


def reset() -> None:
    """Forget all failures (tests)."""
    _state.clear()


def _position(service: str, key: str) -> str:
    keys = settings.api_keys(service)
    return f"#{keys.index(key) + 1}/{len(keys)}" if key in keys else "#?"
