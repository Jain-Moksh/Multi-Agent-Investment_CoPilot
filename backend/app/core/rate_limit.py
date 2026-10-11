"""
Small in-memory sliding-window rate limiter (single server process, resets on restart).

Used by the auth routes against password guessing:
    LOGIN_FAILURES   5 failed logins per email in 15 min, and 20 per client IP in 15 min
                     (the IP limit slows down trying one password against many emails)
    SIGNUPS          10 new accounts per client IP per hour
    SCAN_TEXT        10 /security/scan-text calls per user per minute
A successful login clears that email's failures. Blocked requests get 429 + Retry-After.
"""

import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit, self.window = limit, window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        return hits

    def retry_after(self, key: str) -> int:
        """Seconds until `key` may try again (0 = allowed now)."""
        now = time.monotonic()
        hits = self._prune(key, now)
        if len(hits) < self.limit:
            return 0
        return max(1, int(self.window - (now - hits[0])) + 1)

    def hit(self, key: str) -> None:
        now = time.monotonic()
        self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def clear(self) -> None:
        self._hits.clear()


LOGIN_FAILURES_PER_EMAIL = SlidingWindowLimiter(limit=5, window_seconds=15 * 60)
LOGIN_FAILURES_PER_IP = SlidingWindowLimiter(limit=20, window_seconds=15 * 60)
SIGNUPS_PER_IP = SlidingWindowLimiter(limit=10, window_seconds=60 * 60)
# POST /security/scan-text: each flagged text costs an LLM call. (The chat route counts its
# stored messages in the DB instead; scan-text stores nothing, so it uses this in-memory window.)
SCAN_TEXT_PER_USER = SlidingWindowLimiter(limit=10, window_seconds=60)
CHAT_ANALYSES_PER_USER = SlidingWindowLimiter(limit=10, window_seconds=60 * 60)


def reset_all() -> None:
    """Forget every counter (tests)."""
    for limiter in (LOGIN_FAILURES_PER_EMAIL, LOGIN_FAILURES_PER_IP, SIGNUPS_PER_IP, SCAN_TEXT_PER_USER,
                    CHAT_ANALYSES_PER_USER):
        limiter.clear()
