"""P2-6 document understanding: per-KB chunking config, document graph metadata, parent-child chunks."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024_document_understanding"
down_revision = "0023_knowledge_gaps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_bases", sa.Column(
        "chunking_config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb"),
    ))

    op.add_column("documents", sa.Column("author", sa.String(255), nullable=True))
    op.add_column("documents", sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_documents_department", "documents", "departments",
        ["department_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_documents_department_id", "documents", ["department_id"])
    op.add_column("documents", sa.Column("topic", sa.String(255), nullable=True))
    op.add_column("documents", sa.Column(
        "related_document_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb"),
    ))

    op.add_column("document_chunks", sa.Column(
        "chunk_role", sa.String(16), nullable=False, server_default="normal",
    ))
    op.create_index("ix_document_chunks_chunk_role", "document_chunks", ["chunk_role"])
    op.add_column("document_chunks", sa.Column("parent_sequence_number", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "parent_sequence_number")
    op.drop_index("ix_document_chunks_chunk_role", table_name="document_chunks")
    op.drop_column("document_chunks", "chunk_role")
    op.drop_column("documents", "related_document_ids")
    op.drop_column("documents", "topic")
    op.drop_index("ix_documents_department_id", table_name="documents")
    op.drop_constraint("fk_documents_department", "documents", type_="foreignkey")
    op.drop_column("documents", "department_id")
    op.drop_column("documents", "author")
    op.drop_column("knowledge_bases", "chunking_config")
