"""News articles ingested from GDELT / Google News RSS / Marketaux, and the quarantine."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import SecurityStatus, str_enum


class NewsColumns:
    """
    Article columns shared by news_events and news_quarantine, so a quarantined
    article keeps exactly the shape it had (and the two tables can't drift apart).
    """

    source_api: Mapped[str] = mapped_column(String(32))  # "gdelt" | "google_rss" | "marketaux"
    url: Mapped[str] = mapped_column(Text, unique=True)  # unique => same article is never stored twice
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    # Publisher, e.g. "The Times of India" / "timesofindia.indiatimes.com". Stored
    # separately because Google News URLs are redirects that hide the real domain;
    # the RAG-poisoning source-trust check needs it.
    source_name: Mapped[str | None] = mapped_column(String(255))
    source_domain: Mapped[str | None] = mapped_column(String(255), index=True)

    # Sentiment is a score from -1 (very negative) to +1 (very positive).
    sentiment: Mapped[float | None] = mapped_column(Float)
    affected_sector: Mapped[str | None] = mapped_column(String(64), index=True)
    affected_symbols: Mapped[list[str]] = mapped_column(ARRAY(String(32)), server_default="{}")

    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Prompt-injection scan verdict (NULL = stored before the scanner existed).
    security_status: Mapped[SecurityStatus | None] = mapped_column(
        str_enum(SecurityStatus, "security_status"), index=True
    )
    security_reason: Mapped[str | None] = mapped_column(Text)


class NewsEvent(NewsColumns, Base):
    """
    One news article plus the News Agent's analysis and the injection
    scanner's verdict.

    Ingestion scans every new article (title + description) for prompt
    injection before inserting it (app/security/injection_classifier.py).
    Before embedding, app/security/rag_poisoning.py decides "proceed" or
    "quarantine"; quarantined articles are MOVED to news_quarantine.
    RULE: agents and the RAG pipeline must only read rows where
    security_status = 'safe', so unscanned or flagged text never reaches an LLM.
    """

    __tablename__ = "news_events"
    __table_args__ = (
        CheckConstraint("sentiment BETWEEN -1 AND 1", name="sentiment_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)


class NewsQuarantine(NewsColumns, Base):
    """
    Articles held back from the vector store (RAG poisoning defence): failed the
    injection scan, or untrusted source + part of a near-duplicate cluster.
    No agent has permission to read this table; it exists for review and the
    security dashboard.
    """

    __tablename__ = "news_quarantine"
    __table_args__ = (
        CheckConstraint("sentiment BETWEEN -1 AND 1", name="sentiment_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    original_news_event_id: Mapped[int] = mapped_column(Integer)  # its id in news_events before the move
    quarantine_reason: Mapped[str] = mapped_column(Text)
    quarantined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
