"""company_fundamentals cache table

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FLOAT_COLUMNS = ("pe_ratio", "forward_pe", "price_to_book", "eps", "roe", "debt_to_equity", "dividend_yield_pct",
                 "profit_margin", "revenue_growth", "week52_high", "week52_low")


def upgrade() -> None:
    op.create_table(
        "company_fundamentals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("sector", sa.String(128), nullable=True),
        sa.Column("industry", sa.String(128), nullable=True),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("market_cap", sa.Numeric(22, 2), nullable=True),
        *[sa.Column(column, sa.Float(), nullable=True) for column in FLOAT_COLUMNS],
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_fundamentals")),
        sa.UniqueConstraint("symbol", name=op.f("uq_company_fundamentals_symbol")),
    )


def downgrade() -> None:
    op.drop_table("company_fundamentals")
