"""P2-5 knowledge gap center: persist unanswered / low-confidence / negative feedback issues."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_knowledge_gaps"
down_revision = "0022_chatflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_gaps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("normalized_question", sa.String(255), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="OPEN"),
        sa.Column("assignee_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("linked_document_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("sample_message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sample_answer", sa.Text(), nullable=True),
        sa.Column("latest_answer", sa.Text(), nullable=True),
        sa.Column("latest_confidence", sa.String(16), nullable=True),
        sa.Column("rerun_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("normalized_question", "reason", name="uq_knowledge_gaps_question_reason"),
    )
    op.create_index("ix_knowledge_gaps_normalized_question", "knowledge_gaps", ["normalized_question"])
    op.create_index("ix_knowledge_gaps_reason", "knowledge_gaps", ["reason"])
    op.create_index("ix_knowledge_gaps_status", "knowledge_gaps", ["status"])
    op.create_index("ix_knowledge_gaps_assignee_user_id", "knowledge_gaps", ["assignee_user_id"])
    op.create_index("ix_knowledge_gaps_last_seen_at", "knowledge_gaps", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_gaps_last_seen_at", table_name="knowledge_gaps")
    op.drop_index("ix_knowledge_gaps_assignee_user_id", table_name="knowledge_gaps")
    op.drop_index("ix_knowledge_gaps_status", table_name="knowledge_gaps")
    op.drop_index("ix_knowledge_gaps_reason", table_name="knowledge_gaps")
    op.drop_index("ix_knowledge_gaps_normalized_question", table_name="knowledge_gaps")
    op.drop_table("knowledge_gaps")
