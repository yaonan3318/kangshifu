"""Add durable upload batches and associate existing documents with a legacy batch."""

import uuid
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_upload_batches"
down_revision = "0004_harness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "upload_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(128)), sa.Column("tags", postgresql.JSONB(), nullable=False),
        sa.Column("note", sa.Text()), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_upload_batches_status", "upload_batches", ["status"])
    op.create_table(
        "batch_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("upload_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("relative_path", sa.String(2048), nullable=False), sa.Column("original_name", sa.String(1024), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False), sa.Column("sha256", sa.String(64)),
        sa.Column("upload_status", sa.String(32), nullable=False), sa.Column("processing_status", sa.String(32), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False), sa.Column("error_stage", sa.String(32)),
        sa.Column("error_code", sa.String(64)), sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("batch_id", "relative_path", name="uq_batch_files_path"),
    )
    for name, columns in (("ix_batch_files_batch_id", ["batch_id"]), ("ix_batch_files_document_id", ["document_id"]), ("ix_batch_files_sha256", ["sha256"]), ("ix_batch_files_upload_status", ["upload_status"]), ("ix_batch_files_processing_status", ["processing_status"])):
        op.create_index(name, "batch_files", columns)

    connection = op.get_bind()
    legacy_id = uuid.uuid4()
    connection.execute(sa.text("INSERT INTO upload_batches (id,name,tags,status,completed_at) VALUES (:id,'历史导入','[]'::jsonb,'COMPLETED',now())"), {"id": legacy_id})
    documents = connection.execute(sa.text("SELECT id, original_name, size_bytes, sha256, status, created_at FROM documents")).mappings()
    for document in documents:
        process = "INDEXED" if document["status"] == "READY" else ("FAILED" if document["status"].endswith("FAILED") else "PROCESSING")
        connection.execute(sa.text("""INSERT INTO batch_files (id,batch_id,document_id,relative_path,original_name,size_bytes,sha256,upload_status,processing_status,retry_count,created_at,updated_at) VALUES (:id,:batch,:doc,:path,:name,:size,:sha,'UPLOADED',:processing,0,:created,:created)"""), {"id": uuid.uuid4(), "batch": legacy_id, "doc": document["id"], "path": f"{document['id']}/{document['original_name']}", "name": document["original_name"], "size": document["size_bytes"], "sha": document["sha256"], "processing": process, "created": document["created_at"]})


def downgrade() -> None:
    op.drop_table("batch_files")
    op.drop_table("upload_batches")
