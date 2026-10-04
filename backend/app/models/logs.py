"""Audit trails: what each agent did, and what the security layer caught."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, Text, false, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import SecurityEventType, Severity, str_enum


class AgentLog(Base):
    """One row per agent action (e.g. News Agent -> 'write_news_events')."""

    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(64))
    input_summary: Mapped[str | None] = mapped_column(Text)
    output_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class SecurityLog(Base):
    """
    One row per security event: an injection attempt in news/chat, an agent
    trying an action outside its allow-list, or suspected RAG poisoning.
    This table powers the security demo / dashboard.
    """

    __tablename__ = "security_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[SecurityEventType] = mapped_column(
        str_enum(SecurityEventType, "event_type"), index=True
    )
    severity: Mapped[Severity] = mapped_column(str_enum(Severity, "severity"))
    # Structured context, e.g. {"agent": "news_agent", "attempted_action": "read_portfolio",
    # "matched_pattern": "ignore previous instructions", "content_snippet": "..."}
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    blocked: Mapped[bool] = mapped_column(Boolean, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
