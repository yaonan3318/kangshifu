"""P2-5/P2-6: persistent answer jobs and parent/superseded chunk relationships.

- answer_jobs：把一次问答生成为可恢复、可取消的持久化任务。
- documents.superseded_by_id：替代版本关系。
- document_chunks.parent_chunk_id：父子切片显式关系。
所有新增字段都带 server_default 或可空，历史数据不受影响。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0028_answer_jobs"
down_revision = "0027_reliability_and_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "answer_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("assistants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("current_stage", sa.String(64), nullable=True),
        sa.Column("partial_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("event_cursor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("request_id", name="uq_answer_jobs_request_id"),
    )
    op.create_index("ix_answer_jobs_conversation_id", "answer_jobs", ["conversation_id"])
    op.create_index("ix_answer_jobs_message_id", "answer_jobs", ["message_id"])
    op.create_index("ix_answer_jobs_user_id", "answer_jobs", ["user_id"])
    op.create_index("ix_answer_jobs_assistant_id", "answer_jobs", ["assistant_id"])
    op.create_index("ix_answer_jobs_status", "answer_jobs", ["status"])
    op.create_index("ix_answer_jobs_request_id", "answer_jobs", ["request_id"])

    op.add_column("documents", sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_documents_superseded_by", "documents", "documents",
        ["superseded_by_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_documents_superseded_by_id", "documents", ["superseded_by_id"])
    # 为升级前已经存在的版本链回填“被哪个新版本替代”，否则历史引用会误判为仍有效。
    op.execute(sa.text("""
        UPDATE documents AS previous
        SET superseded_by_id = current.id
        FROM documents AS current
        WHERE current.previous_version_id = previous.id
          AND previous.superseded_by_id IS NULL
    """))

    op.add_column("document_chunks", sa.Column("parent_chunk_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_document_chunks_parent", "document_chunks", "document_chunks",
        ["parent_chunk_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_document_chunks_parent_chunk_id", "document_chunks", ["parent_chunk_id"])
    # 旧数据只有父片段序号；升级时把它转换为稳定的 UUID 外键。
    op.execute(sa.text("""
        UPDATE document_chunks AS child
        SET parent_chunk_id = parent.id
        FROM document_chunks AS parent
        WHERE child.document_id = parent.document_id
          AND child.parent_sequence_number = parent.sequence_number
          AND child.parent_chunk_id IS NULL
    """))


def downgrade() -> None:
    op.drop_index("ix_document_chunks_parent_chunk_id", table_name="document_chunks")
    op.drop_constraint("fk_document_chunks_parent", "document_chunks", type_="foreignkey")
    op.drop_column("document_chunks", "parent_chunk_id")

    op.drop_index("ix_documents_superseded_by_id", table_name="documents")
    op.drop_constraint("fk_documents_superseded_by", "documents", type_="foreignkey")
    op.drop_column("documents", "superseded_by_id")

    op.drop_index("ix_answer_jobs_request_id", table_name="answer_jobs")
    op.drop_index("ix_answer_jobs_status", table_name="answer_jobs")
    op.drop_index("ix_answer_jobs_assistant_id", table_name="answer_jobs")
    op.drop_index("ix_answer_jobs_user_id", table_name="answer_jobs")
    op.drop_index("ix_answer_jobs_message_id", table_name="answer_jobs")
    op.drop_index("ix_answer_jobs_conversation_id", table_name="answer_jobs")
    op.drop_table("answer_jobs")
