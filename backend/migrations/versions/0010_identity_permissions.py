"""Add users, departments, roles, document ACLs, auth sessions, and document visibility."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0010_identity_permissions"
down_revision = "0009_assistants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("departments.id", ondelete="SET NULL")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_departments_parent_id", "departments", ["parent_id"])

    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("departments.id", ondelete="SET NULL")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_super_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_department_id", "users", ["department_id"])

    op.create_table(
        "user_roles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "document_acl",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_type", sa.String(16), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission", sa.String(16), nullable=False, server_default="READ"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_document_acl_document_id", "document_acl", ["document_id"])
    op.create_index("ix_document_acl_subject_id", "document_acl", ["subject_id"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", sa.String(64)),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])

    # 历史资料默认对全公司可见，保证升级后原有资料检索不受影响。
    op.add_column("documents", sa.Column("visibility", sa.String(16), nullable=False, server_default="COMPANY"))
    op.add_column("documents", sa.Column("owner_user_id", postgresql.UUID(as_uuid=True)))
    op.create_index("ix_documents_visibility", "documents", ["visibility"])
    op.create_index("ix_documents_owner_user_id", "documents", ["owner_user_id"])
    op.create_foreign_key("fk_documents_owner_user", "documents", "users", ["owner_user_id"], ["id"], ondelete="SET NULL")

    op.create_foreign_key("fk_chat_sessions_user", "chat_sessions", "users", ["user_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_chat_sessions_user", "chat_sessions", type_="foreignkey")
    op.drop_constraint("fk_documents_owner_user", "documents", type_="foreignkey")
    op.drop_index("ix_documents_owner_user_id", table_name="documents")
    op.drop_index("ix_documents_visibility", table_name="documents")
    op.drop_column("documents", "owner_user_id")
    op.drop_column("documents", "visibility")
    op.drop_table("auth_sessions")
    op.drop_table("document_acl")
    op.drop_table("user_roles")
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("departments")
