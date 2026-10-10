"""AI Assistant conversations (DB-backed, so history survives restarts and is auditable)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import SecurityStatus, str_enum


class ChatConversation(Base):
    """One conversation; `id` is a random UUID hex the client sends back for follow-ups."""

    __tablename__ = "chat_conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="ChatMessage.id"
    )


class ChatMessage(Base):
    """
    One message. User messages carry the injection-scan verdict; BLOCKED ones are kept for
    the audit trail but never sent to the LLM, now or as history later.
    """

    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_conversation_id_id", "conversation_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("chat_conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    security_status: Mapped[SecurityStatus | None] = mapped_column(str_enum(SecurityStatus, "security_status"))
    security_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    conversation: Mapped[ChatConversation] = relationship(back_populates="messages")


class ChatLog(Base):
    """
    One row per chat exchange (message + reply), for later reference and evaluation:
    what was asked, which stocks were detected, exactly which context the LLM got
    (news ids, recommendation id, portfolio analysis), the verdict, outcome and latency.
    Refused (BLOCKED) exchanges are logged too.
    """

    __tablename__ = "chat_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("chat_conversations.id", ondelete="CASCADE"), index=True)
    user_message_id: Mapped[int | None] = mapped_column(Integer)
    assistant_message_id: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    reply: Mapped[str] = mapped_column(Text)
    security_verdict: Mapped[str] = mapped_column(String(16))   # SAFE | SUSPICIOUS | BLOCKED
    status: Mapped[str] = mapped_column(String(32))             # ok | refused | llm_unavailable | blocked_output
    mode: Mapped[str] = mapped_column(String(16))               # symbol | general | refused
    detected_symbols: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    context_used: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
