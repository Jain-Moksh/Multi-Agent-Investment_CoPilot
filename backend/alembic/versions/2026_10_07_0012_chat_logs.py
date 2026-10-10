"""chat_logs table (one row per chat exchange)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(32), nullable=False),
        sa.Column("user_message_id", sa.Integer(), nullable=True),
        sa.Column("assistant_message_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("reply", sa.Text(), nullable=False),
        sa.Column("security_verdict", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("detected_symbols", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("context_used", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_logs")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_chat_logs_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"],
                                name=op.f("fk_chat_logs_conversation_id_chat_conversations"), ondelete="CASCADE"),
    )
    for column in ("user_id", "conversation_id", "created_at"):
        op.create_index(op.f(f"ix_chat_logs_{column}"), "chat_logs", [column])


def downgrade() -> None:
    op.drop_table("chat_logs")
