"""news_events: allow unscanned rows (NULL security_status), add source_name/source_domain

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-02

Ingestion now stores raw articles first; the security scanner (Phase 4) fills
security_status afterwards. NULL means "not scanned yet".
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("news_events", sa.Column("source_name", sa.String(255), nullable=True))
    op.add_column("news_events", sa.Column("source_domain", sa.String(255), nullable=True))
    op.create_index("ix_news_events_source_domain", "news_events", ["source_domain"])
    op.alter_column("news_events", "security_status", existing_type=sa.String(32), nullable=True)


def downgrade() -> None:
    # Unscanned rows can't satisfy NOT NULL; mark them suspicious (the conservative choice).
    op.execute("UPDATE news_events SET security_status = 'suspicious' WHERE security_status IS NULL")
    op.alter_column("news_events", "security_status", existing_type=sa.String(32), nullable=False)
    op.drop_index("ix_news_events_source_domain", table_name="news_events")
    op.drop_column("news_events", "source_domain")
    op.drop_column("news_events", "source_name")
