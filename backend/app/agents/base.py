"""
Shared pieces for every specialist agent.

Common result fields (so the Agreement & Confidence module can compare agents):
    agent       which agent produced it
    symbol      the stock analysed
    status      "ok" or why the analysis is degraded ("no_news", "llm_unavailable", ...)
    signal      -1.0 (strongly bearish) .. 0 (neutral) .. +1.0 (strongly bullish)
    confidence  0.0 (ignore me) .. 1.0 (strong evidence)
    rationale   one or two plain-English sentences

Audit logging: every agent call is recorded in agent_logs. This is a system
function, not an agent action, so it is NOT subject to the agent permission
allow-lists (no agent is allowed to write agent_logs), and a failed log write
never breaks the analysis.
"""

import json
import logging
import re
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import AsyncSessionLocal
from app.models import AgentLog

logger = logging.getLogger(__name__)

MAX_LOG_CHARS = 2000


class BaseAgent:
    name: str = "base_agent"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal):
        self.session_factory = session_factory

    async def log_call(self, action: str, input_summary: dict[str, Any], output_summary: dict[str, Any]) -> None:
        """Write one agent_logs row (own transaction; never raises)."""
        try:
            async with self.session_factory() as db:
                db.add(
                    AgentLog(
                        agent_name=self.name,
                        action=action,
                        input_summary=json.dumps(input_summary, default=str)[:MAX_LOG_CHARS],
                        output_summary=json.dumps(output_summary, default=str)[:MAX_LOG_CHARS],
                    )
                )
                await db.commit()
        except Exception:
            logger.exception("[%s] could not write agent_logs row for %s", self.name, action)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def untrusted_block(label: str, body: str) -> tuple[str, str]:
    """
    Wrap untrusted text (articles, user messages) in markers containing a random
    nonce, so text inside can't fake the end of the block. Returns (block, nonce).
    """
    nonce = secrets.token_hex(8)
    return f"<<<{label} {nonce}>>>\n{body}\n<<<END {label} {nonce}>>>", nonce


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_json_object(text: str) -> dict[str, Any]:
    """
    Parse an LLM's JSON reply. Tolerates ```json fences and text around the object.
    Raises ValueError if no JSON object can be read.
    """
    cleaned = _FENCE.sub("", text.strip())
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object in LLM reply") from None
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in LLM reply: {exc}") from None
    if not isinstance(value, dict):
        raise ValueError("LLM reply is JSON but not an object")
    return value
