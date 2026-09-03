"""Add local keyword and vector search indexes."""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0003_hybrid_search"
down_revision = "0002_processing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE document_chunks ADD COLUMN search_vector tsvector")
    op.execute("ALTER TABLE document_chunks ADD COLUMN embedding vector(1024)")
    op.execute("CREATE INDEX ix_document_chunks_search_vector ON document_chunks USING gin (search_vector)")
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding_hnsw ON document_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    connection = op.get_bind()
    parsed_ids = connection.execute(sa.text("SELECT id FROM documents WHERE status = 'PARSED'"))
    for document_id in parsed_ids.scalars():
        connection.execute(
            sa.text(
                "INSERT INTO processing_jobs "
                "(id, document_id, job_type, status, attempts, created_at) "
                "VALUES (:id, :document_id, 'INDEX', 'QUEUED', 0, now())"
            ),
            {"id": uuid.uuid4(), "document_id": document_id},
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_search_vector")
    op.drop_column("document_chunks", "embedding")
    op.drop_column("document_chunks", "search_vector")
