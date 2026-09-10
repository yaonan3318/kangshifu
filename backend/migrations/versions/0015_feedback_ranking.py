"""Feedback ranking support: aggregation indexes and stored document feedback stats."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0015_feedback_ranking"
down_revision = "0014_audit_completion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 反馈排序第一版默认关闭；这里先建立可支撑聚合的索引与统计表。
    op.add_column(
        "answer_feedback",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="SET NULL")),
    )
    op.create_index("ix_answer_feedback_rating", "answer_feedback", ["rating"])
    op.create_index("ix_answer_feedback_document_id", "answer_feedback", ["document_id"])
    op.create_index(
        "ix_chat_message_sources_document_message",
        "chat_message_sources",
        ["document_id", "message_id"],
    )

    op.create_table(
        "document_feedback_stats",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("up_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("down_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("document_feedback_stats")
    op.drop_index("ix_chat_message_sources_document_message", table_name="chat_message_sources")
    op.drop_index("ix_answer_feedback_document_id", table_name="answer_feedback")
    op.drop_index("ix_answer_feedback_rating", table_name="answer_feedback")
    op.drop_column("answer_feedback", "document_id")
