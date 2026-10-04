"""portfolio_holdings.source, transactions.external_id, broker_connections

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03

- portfolio_holdings gets a `source` (manual / tradebook_upload / kite_sync) and
  the unique key becomes (user_id, asset_type, symbol, source), so Zerodha-synced
  rows never overwrite manually entered ones.
- transactions gets `external_id` (broker trade id) + unique key for de-duplication.
- broker_connections stores each user's encrypted Kite access token.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "broker_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("broker", sa.String(32), nullable=False),
        sa.Column("broker_user_id", sa.String(64), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_broker_connections"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_broker_connections_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("user_id", "broker", name="uq_broker_connections_user_broker"),
    )

    op.add_column(
        "portfolio_holdings",
        sa.Column("source", sa.String(32), server_default="manual", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_portfolio_holdings_source"),
        "portfolio_holdings",
        "source IN ('manual', 'tradebook_upload', 'kite_sync')",
    )
    op.drop_constraint("uq_portfolio_holdings_user_asset_symbol", "portfolio_holdings", type_="unique")
    op.create_unique_constraint(
        "uq_portfolio_holdings_user_asset_symbol_source",
        "portfolio_holdings",
        ["user_id", "asset_type", "symbol", "source"],
    )

    op.add_column("transactions", sa.Column("external_id", sa.String(64), nullable=True))
    op.create_unique_constraint(
        "uq_transactions_user_source_external_id", "transactions", ["user_id", "source", "external_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_transactions_user_source_external_id", "transactions", type_="unique")
    op.drop_column("transactions", "external_id")

    # The old key (user_id, asset_type, symbol) can't hold a manual AND a synced row
    # for the same stock; synced rows can be re-created by syncing again.
    op.execute("DELETE FROM portfolio_holdings WHERE source <> 'manual'")
    op.drop_constraint("uq_portfolio_holdings_user_asset_symbol_source", "portfolio_holdings", type_="unique")
    op.create_unique_constraint(
        "uq_portfolio_holdings_user_asset_symbol", "portfolio_holdings", ["user_id", "asset_type", "symbol"]
    )
    op.drop_constraint(op.f("ck_portfolio_holdings_source"), "portfolio_holdings", type_="check")
    op.drop_column("portfolio_holdings", "source")

    op.drop_table("broker_connections")
