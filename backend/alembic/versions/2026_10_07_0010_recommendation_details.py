"""recommendations: overall_lean + details (decision inputs, for audit and SHAP/LIME)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recommendations", sa.Column("overall_lean", sa.Float(), nullable=True))
    op.add_column("recommendations", sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_check_constraint(
        op.f("ck_recommendations_overall_lean_range"), "recommendations", "overall_lean BETWEEN -1 AND 1"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_recommendations_overall_lean_range"), "recommendations", type_="check")
    op.drop_column("recommendations", "details")
    op.drop_column("recommendations", "overall_lean")
