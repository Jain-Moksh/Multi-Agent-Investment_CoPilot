"""Request/response bodies for /security (the security dashboard)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SecurityEventOut(BaseModel):
    id: int
    event_type: str        # prompt_injection | agent_hijack | rag_poison
    severity: str          # low | medium | high | critical
    blocked: bool
    details: dict[str, Any]
    created_at: datetime


class QuarantineItemOut(BaseModel):
    id: int
    original_news_event_id: int
    title: str
    url: str
    description: str | None
    source_api: str
    source_name: str | None
    source_domain: str | None
    affected_symbols: list[str]
    security_status: str | None   # the injection verdict the article had (often "safe" for duplicate clusters)
    quarantine_reason: str
    seen_at: datetime
    quarantined_at: datetime


class SecurityStats(BaseModel):
    events_total: int
    events_by_type: dict[str, int]    # every type is present, 0 when none
    blocked_count: int                # security_logs rows with blocked = true
    quarantine_count: int             # rows in news_quarantine
    safe_news_count: int              # news_events with security_status = 'safe'


class ScanTextIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ScanTextOut(BaseModel):
    verdict: str                      # SAFE | SUSPICIOUS | BLOCKED
    stage: str                        # rules | llm
    matched_patterns: list[str]
    reason: str
