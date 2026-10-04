"""user_profiles: stated_* preferences, profile_basis, behavior_metrics, classified_at

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-04

Separates what the user stated from the effective profile the User Profiling
Agent computes. Existing risk_appetite / investment_horizon values could only
have come from the user, so they are copied into the new stated_* columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("stated_risk_appetite", sa.String(32), nullable=True))
    op.add_column("user_profiles", sa.Column("stated_investment_horizon", sa.String(32), nullable=True))
    op.add_column("user_profiles", sa.Column("profile_basis", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("user_profiles", sa.Column("behavior_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("user_profiles", sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_user_profiles_stated_risk_appetite"), "user_profiles",
        "stated_risk_appetite IN ('conservative', 'moderate', 'aggressive')",
    )
    op.create_check_constraint(
        op.f("ck_user_profiles_stated_investment_horizon"), "user_profiles",
        "stated_investment_horizon IN ('short_term', 'medium_term', 'long_term')",
    )
    op.execute(
        "UPDATE user_profiles SET stated_risk_appetite = risk_appetite, "
        "stated_investment_horizon = investment_horizon"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_user_profiles_stated_investment_horizon"), "user_profiles", type_="check")
    op.drop_constraint(op.f("ck_user_profiles_stated_risk_appetite"), "user_profiles", type_="check")
    for column in ("classified_at", "behavior_metrics", "profile_basis", "stated_investment_horizon",
                   "stated_risk_appetite"):
        op.drop_column("user_profiles", column)
