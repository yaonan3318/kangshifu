"""Add parsed document chunks and processing states."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_processing"
down_revision = "0001_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer()),
        sa.Column("page_end", sa.Integer()),
        sa.Column("slide_number", sa.Integer()),
        sa.Column("sheet_name", sa.String(255)),
        sa.Column("row_start", sa.Integer()),
        sa.Column("row_end", sa.Integer()),
        sa.Column("section_path", postgresql.ARRAY(sa.String(512)), nullable=False, server_default="{}"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("ocr_confidence", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("document_id", "sequence_number", name="uq_chunk_document_sequence"),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])


def downgrade() -> None:
    op.drop_table("document_chunks")

