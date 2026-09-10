"""Identity management completion: department timestamps/uniqueness and role enable flags."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0013_identity_management"
down_revision = "0012_answer_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 部门：补齐 updated_at，并约束名称唯一，避免管理员创建重名部门。
    op.add_column(
        "departments",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_departments_name", "departments", ["name"])

    # 角色：补齐启停字段与更新时间；停用角色不再参与权限判断，但历史 ACL 保留。
    op.add_column(
        "roles",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "roles",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_roles_enabled", "roles", ["enabled"])

    # 帮助 ACL 去重与权限判断的复合索引。
    op.create_index(
        "ix_document_acl_lookup",
        "document_acl",
        ["document_id", "subject_type", "subject_id", "permission"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_acl_lookup", table_name="document_acl")
    op.drop_index("ix_roles_enabled", table_name="roles")
    op.drop_column("roles", "updated_at")
    op.drop_column("roles", "enabled")
    op.drop_constraint("uq_departments_name", "departments", type_="unique")
    op.drop_column("departments", "updated_at")
