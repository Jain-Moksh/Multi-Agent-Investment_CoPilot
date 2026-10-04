"""initial schema: users, profiles, portfolio, news, market, logs, recommendations

Revision ID: 0001
Revises:
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    # ---------------- users & profiles ----------------
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("risk_appetite", sa.String(32), nullable=True),
        sa.Column("investment_horizon", sa.String(32), nullable=True),
        sa.Column("goals", sa.Text(), nullable=True),
        sa.Column("monthly_investment_amount", sa.Numeric(14, 2), nullable=True),
        _created_at("updated_at"),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_profiles"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_profiles_user_id_users", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "risk_appetite IN ('conservative', 'moderate', 'aggressive')",
            name=op.f("ck_user_profiles_risk_appetite"),
        ),
        sa.CheckConstraint(
            "investment_horizon IN ('short_term', 'medium_term', 'long_term')",
            name=op.f("ck_user_profiles_investment_horizon"),
        ),
    )

    # ---------------- portfolio ----------------
    op.create_table(
        "portfolio_holdings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("avg_buy_price", sa.Numeric(18, 4), nullable=False),
        _created_at("added_at"),
        sa.PrimaryKeyConstraint("id", name="pk_portfolio_holdings"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_portfolio_holdings_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "user_id", "asset_type", "symbol", name="uq_portfolio_holdings_user_asset_symbol"
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_portfolio_holdings_quantity_positive")),
        sa.CheckConstraint("avg_buy_price >= 0", name=op.f("ck_portfolio_holdings_avg_buy_price_non_negative")),
        sa.CheckConstraint(
            "asset_type IN ('stock', 'mutual_fund', 'fd', 'gold', 'property')",
            name=op.f("ck_portfolio_holdings_asset_type"),
        ),
    )
    op.create_index("ix_portfolio_holdings_user_id", "portfolio_holdings", ["user_id"])

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("price", sa.Numeric(18, 4), nullable=False),
        sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_transactions_user_id_users", ondelete="CASCADE"
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_transactions_quantity_positive")),
        sa.CheckConstraint("price >= 0", name=op.f("ck_transactions_price_non_negative")),
        sa.CheckConstraint("action IN ('buy', 'sell')", name=op.f("ck_transactions_action")),
        sa.CheckConstraint(
            "source IN ('manual', 'tradebook_upload', 'kite_sync')", name=op.f("ck_transactions_source")
        ),
    )
    op.create_index(
        "ix_transactions_user_id_transaction_date", "transactions", ["user_id", "transaction_date"]
    )

    # ---------------- news & market data ----------------
    op.create_table(
        "news_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_api", sa.String(32), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sentiment", sa.Float(), nullable=True),
        sa.Column("affected_sector", sa.String(64), nullable=True),
        sa.Column(
            "affected_symbols", postgresql.ARRAY(sa.String(32)), server_default="{}", nullable=False
        ),
        _created_at("seen_at"),
        sa.Column("security_status", sa.String(32), nullable=False),
        sa.Column("security_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_news_events"),
        sa.UniqueConstraint("url", name="uq_news_events_url"),
        sa.CheckConstraint("sentiment BETWEEN -1 AND 1", name=op.f("ck_news_events_sentiment_range")),
        sa.CheckConstraint(
            "security_status IN ('safe', 'suspicious', 'blocked')",
            name=op.f("ck_news_events_security_status"),
        ),
    )
    op.create_index("ix_news_events_seen_at", "news_events", ["seen_at"])
    op.create_index("ix_news_events_affected_sector", "news_events", ["affected_sector"])
    op.create_index("ix_news_events_security_status", "news_events", ["security_status"])

    op.create_table(
        "market_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("price", sa.Numeric(18, 4), nullable=False),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        _created_at("fetched_at"),
        sa.PrimaryKeyConstraint("id", name="pk_market_snapshots"),
    )
    op.create_index(
        "ix_market_snapshots_symbol_fetched_at", "market_snapshots", ["symbol", "fetched_at"]
    )

    # ---------------- audit logs ----------------
    op.create_table(
        "agent_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_agent_logs"),
    )
    op.create_index("ix_agent_logs_agent_name", "agent_logs", ["agent_name"])
    op.create_index("ix_agent_logs_created_at", "agent_logs", ["created_at"])

    op.create_table(
        "security_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column(
            "details", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("blocked", sa.Boolean(), server_default=sa.false(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_security_logs"),
        sa.CheckConstraint(
            "event_type IN ('prompt_injection', 'agent_hijack', 'rag_poison')",
            name=op.f("ck_security_logs_event_type"),
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')", name=op.f("ck_security_logs_severity")
        ),
    )
    op.create_index("ix_security_logs_event_type", "security_logs", ["event_type"])
    op.create_index("ix_security_logs_created_at", "security_logs", ["created_at"])

    # ---------------- recommendations ----------------
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_recommendations"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_recommendations_user_id_users", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "confidence_score BETWEEN 0 AND 1", name=op.f("ck_recommendations_confidence_range")
        ),
        sa.CheckConstraint("decision IN ('buy', 'hold', 'sell')", name=op.f("ck_recommendations_decision")),
    )
    op.create_index(
        "ix_recommendations_user_id_created_at", "recommendations", ["user_id", "created_at"]
    )


def downgrade() -> None:
    # Drop in reverse dependency order (children before users).
    op.drop_table("recommendations")
    op.drop_table("security_logs")
    op.drop_table("agent_logs")
    op.drop_table("market_snapshots")
    op.drop_table("news_events")
    op.drop_table("transactions")
    op.drop_table("portfolio_holdings")
    op.drop_table("user_profiles")
    op.drop_table("users")
