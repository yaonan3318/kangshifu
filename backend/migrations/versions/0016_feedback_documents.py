"""Multi-document feedback attribution: link a feedback to every cited document.

反馈排序第一版默认关闭；本迁移只新增关联表并把已有单文档反馈回填进去，
不改动、不删除任何现有反馈数据。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0016_feedback_documents"
down_revision = "0015_feedback_ranking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "answer_feedback_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "feedback_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("answer_feedback.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "document_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("citation_number", sa.Integer(), nullable=True),
        sa.UniqueConstraint("feedback_id", "document_id", name="uq_answer_feedback_documents"),
    )
    op.create_index(
        "ix_answer_feedback_documents_feedback_id", "answer_feedback_documents", ["feedback_id"]
    )
    op.create_index(
        "ix_answer_feedback_documents_document_id", "answer_feedback_documents", ["document_id"]
    )
    # 回填历史单文档反馈，避免升级后排序统计丢失旧数据。
    op.execute(
        """
        INSERT INTO answer_feedback_documents (id, feedback_id, document_id, citation_number)
        SELECT gen_random_uuid(), id, document_id, NULL
        FROM answer_feedback
        WHERE document_id IS NOT NULL
        ON CONFLICT (feedback_id, document_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_answer_feedback_documents_document_id", table_name="answer_feedback_documents")
    op.drop_index("ix_answer_feedback_documents_feedback_id", table_name="answer_feedback_documents")
    op.drop_table("answer_feedback_documents")
