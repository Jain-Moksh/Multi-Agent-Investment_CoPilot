"""chat_conversations + chat_messages (AI Assistant history)

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_conversations")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_chat_conversations_user_id_users"),
                                ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_chat_conversations_user_id"), "chat_conversations", ["user_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(32), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("security_status", sa.String(32), nullable=True),
        sa.Column("security_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"],
                                name=op.f("fk_chat_messages_conversation_id_chat_conversations"), ondelete="CASCADE"),
        sa.CheckConstraint("security_status IN ('safe', 'suspicious', 'blocked')",
                           name=op.f("ck_chat_messages_security_status")),
    )
    op.create_index(op.f("ix_chat_messages_created_at"), "chat_messages", ["created_at"])
    op.create_index("ix_chat_messages_conversation_id_id", "chat_messages", ["conversation_id", "id"])


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_conversations")
