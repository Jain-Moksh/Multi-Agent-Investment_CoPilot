"""news_quarantine table (RAG poisoning defence)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-04

Same article columns as news_events, plus where it came from
(original_news_event_id), why it was held back (quarantine_reason) and when.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXED = ("affected_sector", "quarantined_at", "security_status", "seen_at", "source_domain")


def upgrade() -> None:
    op.create_table(
        "news_quarantine",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("original_news_event_id", sa.Integer(), nullable=False),
        sa.Column("quarantine_reason", sa.Text(), nullable=False),
        sa.Column("quarantined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # --- same columns as news_events ---
        sa.Column("source_api", sa.String(32), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_name", sa.String(255), nullable=True),
        sa.Column("source_domain", sa.String(255), nullable=True),
        sa.Column("sentiment", sa.Float(), nullable=True),
        sa.Column("affected_sector", sa.String(64), nullable=True),
        sa.Column("affected_symbols", postgresql.ARRAY(sa.String(32)), server_default="{}", nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("security_status", sa.String(32), nullable=True),
        sa.Column("security_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_news_quarantine")),
        sa.UniqueConstraint("url", name=op.f("uq_news_quarantine_url")),
        sa.CheckConstraint("sentiment BETWEEN -1 AND 1", name=op.f("ck_news_quarantine_sentiment_range")),
        sa.CheckConstraint(
            "security_status IN ('safe', 'suspicious', 'blocked')", name=op.f("ck_news_quarantine_security_status")
        ),
    )
    for column in INDEXED:
        op.create_index(op.f(f"ix_news_quarantine_{column}"), "news_quarantine", [column])


def downgrade() -> None:
    op.drop_table("news_quarantine")  # drops its indexes and constraints too
