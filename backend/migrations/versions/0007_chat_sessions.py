"""Add persistent chat sessions, messages, and answer source snapshots."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0007_chat_sessions"
down_revision = "0006_knowledge_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False, server_default="新会话"),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True)),
        sa.Column("user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    op.create_index("ix_chat_sessions_assistant_id", "chat_sessions", ["assistant_id"])
    op.create_index("ix_chat_sessions_updated_at", "chat_sessions", ["updated_at"])
    op.create_index("ix_chat_sessions_last_message_at", "chat_sessions", ["last_message_at"])
    op.create_index("ix_chat_sessions_archived_at", "chat_sessions", ["archived_at"])

    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(16)),
        sa.Column("knowledge_scope", sa.String(32)),
        sa.Column("status", sa.String(16), nullable=False, server_default="COMPLETED"),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])
    op.create_index("ix_chat_messages_role", "chat_messages", ["role"])

    op.create_table(
        "chat_message_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("citation_number", sa.Integer(), nullable=False),
        sa.Column("document_name", sa.String(1024), nullable=False),
        sa.Column("content_snapshot", sa.Text(), nullable=False),
        sa.Column("location_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("score", sa.Float()),
    )
    op.create_index("ix_chat_message_sources_message_id", "chat_message_sources", ["message_id"])
    op.create_index("ix_chat_message_sources_document_id", "chat_message_sources", ["document_id"])
    op.create_index("ix_chat_message_sources_chunk_id", "chat_message_sources", ["chunk_id"])


def downgrade() -> None:
    op.drop_table("chat_message_sources")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
