"""Add knowledge governance, chunk editing, and retrieval evaluation tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0006_knowledge_governance"
down_revision = "0005_upload_batches"
branch_labels = None
depends_on = None

DEFAULT_KNOWLEDGE_BASE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_knowledge_bases_name"),
    )
    op.create_index("ix_knowledge_bases_name", "knowledge_bases", ["name"])
    op.create_index("ix_knowledge_bases_enabled", "knowledge_bases", ["enabled"])
    op.execute(sa.text(
        "INSERT INTO knowledge_bases (id, name, description, enabled) "
        "VALUES (:id, '默认知识库', '升级前及未指定知识库的公司资料', true)"
    ).bindparams(id=DEFAULT_KNOWLEDGE_BASE_ID))

    op.add_column("upload_batches", sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(sa.text("UPDATE upload_batches SET knowledge_base_id = :id").bindparams(id=DEFAULT_KNOWLEDGE_BASE_ID))
    op.alter_column("upload_batches", "knowledge_base_id", nullable=False)
    op.create_foreign_key("fk_upload_batches_knowledge_base", "upload_batches", "knowledge_bases", ["knowledge_base_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_upload_batches_knowledge_base_id", "upload_batches", ["knowledge_base_id"])

    op.add_column("documents", sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("documents", sa.Column("relative_path", sa.String(2048)))
    op.add_column("documents", sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("documents", sa.Column("previous_version_id", postgresql.UUID(as_uuid=True)))
    op.add_column("documents", sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("documents", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("documents", sa.Column("deleted_reason", sa.Text()))
    op.add_column("documents", sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.execute(sa.text("UPDATE documents SET knowledge_base_id = :id").bindparams(id=DEFAULT_KNOWLEDGE_BASE_ID))
    op.alter_column("documents", "knowledge_base_id", nullable=False)
    op.create_foreign_key("fk_documents_knowledge_base", "documents", "knowledge_bases", ["knowledge_base_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_documents_previous_version", "documents", "documents", ["previous_version_id"], ["id"], ondelete="SET NULL")
    for name, cols in (
        ("ix_documents_knowledge_base_id", ["knowledge_base_id"]), ("ix_documents_previous_version_id", ["previous_version_id"]),
        ("ix_documents_enabled", ["enabled"]), ("ix_documents_deleted_at", ["deleted_at"]),
    ):
        op.create_index(name, "documents", cols)

    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("knowledge_base_id", "name", name="uq_tags_knowledge_base_name"),
    )
    op.create_index("ix_tags_knowledge_base_id", "tags", ["knowledge_base_id"])
    op.create_table(
        "document_tags",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    )

    op.add_column("document_chunks", sa.Column("original_content", sa.Text()))
    op.add_column("document_chunks", sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("document_chunks", sa.Column("manually_edited", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("document_chunks", sa.Column("token_count", sa.Integer()))
    op.add_column("document_chunks", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_document_chunks_enabled", "document_chunks", ["enabled"])

    op.create_table(
        "retrieval_test_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="SET NULL")),
        sa.Column("expected_document_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("expected_keywords", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("expected_no_answer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_retrieval_test_cases_knowledge_base_id", "retrieval_test_cases", ["knowledge_base_id"])
    op.create_index("ix_retrieval_test_cases_enabled", "retrieval_test_cases", ["enabled"])
    op.create_table(
        "retrieval_test_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("settings_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("results", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metrics", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_retrieval_test_runs_created_at", "retrieval_test_runs", ["created_at"])


def downgrade() -> None:
    op.drop_table("retrieval_test_runs")
    op.drop_table("retrieval_test_cases")
    op.drop_index("ix_document_chunks_enabled", table_name="document_chunks")
    for column in ("updated_at", "token_count", "manually_edited", "enabled", "original_content"):
        op.drop_column("document_chunks", column)
    op.drop_table("document_tags")
    op.drop_table("tags")
    op.drop_index("ix_upload_batches_knowledge_base_id", table_name="upload_batches")
    op.drop_constraint("fk_upload_batches_knowledge_base", "upload_batches", type_="foreignkey")
    op.drop_column("upload_batches", "knowledge_base_id")
    for name in ("ix_documents_deleted_at", "ix_documents_enabled", "ix_documents_previous_version_id", "ix_documents_knowledge_base_id"):
        op.drop_index(name, table_name="documents")
    op.drop_constraint("fk_documents_previous_version", "documents", type_="foreignkey")
    op.drop_constraint("fk_documents_knowledge_base", "documents", type_="foreignkey")
    for column in ("metadata", "deleted_reason", "deleted_at", "enabled", "previous_version_id", "version_number", "relative_path", "knowledge_base_id"):
        op.drop_column("documents", column)
    op.drop_table("knowledge_bases")
