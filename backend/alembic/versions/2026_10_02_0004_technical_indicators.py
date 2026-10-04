"""technical_indicators table (Alpha Vantage cache), market_snapshots.source

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "technical_indicators",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("indicator", sa.String(32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_technical_indicators"),
        sa.UniqueConstraint("symbol", "indicator", name="uq_technical_indicators_symbol_indicator"),
    )
    op.add_column("market_snapshots", sa.Column("source", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("market_snapshots", "source")
    op.drop_table("technical_indicators")
