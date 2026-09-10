"""Function-level RBAC: permission catalog, role_permissions and default roles.

只新增两张表并幂等写入权限码与默认角色；不修改现有用户、角色绑定、文档 ACL。
downgrade 仅删除本迁移新增的两张表，保留角色记录，避免破坏既有用户分配。
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018_function_rbac"
down_revision = "0017_assistant_runtime_policy"
branch_labels = None
depends_on = None


# 冻结的权限码目录：与 app/services/rbac.py 保持一致。
PERMISSIONS = [
    {"code": "ANSWER_USE", "name": "知识问答", "category": "basic", "sort_order": 10,
     "description": "使用知识问答与助手进行提问"},
    {"code": "SEARCH_USE", "name": "资料检索", "category": "basic", "sort_order": 20,
     "description": "使用关键词与语义混合检索"},
    {"code": "DOCUMENT_VIEW", "name": "查看资料", "category": "basic", "sort_order": 30,
     "description": "查看自己有权访问的资料"},
    {"code": "DOCUMENT_UPLOAD", "name": "上传资料", "category": "document", "sort_order": 40,
     "description": "上传单文件与批量导入资料"},
    {"code": "DOCUMENT_MANAGE", "name": "管理资料", "category": "document", "sort_order": 50,
     "description": "编辑、启停、删除、恢复及设置文档权限"},
    {"code": "KNOWLEDGE_BASE_MANAGE", "name": "管理知识库", "category": "document", "sort_order": 60,
     "description": "创建、编辑与启停知识库"},
    {"code": "RETRIEVAL_LAB_USE", "name": "检索实验室", "category": "operations", "sort_order": 70,
     "description": "使用检索诊断与评测工具"},
    {"code": "ASSISTANT_MANAGE", "name": "助手管理", "category": "operations", "sort_order": 80,
     "description": "创建、编辑、启停助手并绑定知识库"},
    {"code": "IDENTITY_MANAGE", "name": "身份与角色管理", "category": "operations", "sort_order": 90,
     "description": "管理用户、部门、角色与角色权限"},
    {"code": "AUDIT_VIEW", "name": "审计日志", "category": "operations", "sort_order": 100,
     "description": "查看审计日志"},
    {"code": "STATS_VIEW", "name": "运营统计", "category": "operations", "sort_order": 110,
     "description": "查看运营统计与问答追踪"},
    {"code": "HARNESS_USE", "name": "Harness 运维", "category": "harness", "sort_order": 120,
     "description": "执行 Kubernetes 运维工具（仅超级管理员）"},
]

_BASE = ["ANSWER_USE", "SEARCH_USE", "DOCUMENT_VIEW"]
_MAINTAINER = [*_BASE, "DOCUMENT_UPLOAD", "DOCUMENT_MANAGE"]
_KB_ADMIN = [*_MAINTAINER, "KNOWLEDGE_BASE_MANAGE"]
_SYSTEM_ADMIN = [item["code"] for item in PERMISSIONS if item["code"] != "HARNESS_USE"]

DEFAULT_ROLES = [
    {"name": "普通员工", "description": "日常问答与查看有权资料", "permissions": _BASE},
    {"name": "资料维护员", "description": "在普通员工基础上上传与管理资料", "permissions": _MAINTAINER},
    {"name": "知识库管理员", "description": "在资料维护员基础上管理知识库", "permissions": _KB_ADMIN},
    {"name": "系统管理员", "description": "除 Harness 外的全部后台管理权限", "permissions": _SYSTEM_ADMIN},
]


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("code", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission_code", sa.String(length=64),
                  sa.ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True),
    )

    conn = op.get_bind()
    # 幂等写入权限码：重复执行只更新元数据，不会产生重复行。
    conn.execute(
        sa.text(
            "INSERT INTO permissions (code, name, description, category, sort_order) "
            "VALUES (:code, :name, :description, :category, :sort_order) "
            "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, "
            "description = EXCLUDED.description, category = EXCLUDED.category, "
            "sort_order = EXCLUDED.sort_order"
        ),
        PERMISSIONS,
    )

    for role in DEFAULT_ROLES:
        role_id = conn.execute(
            sa.text("SELECT id FROM roles WHERE name = :name"), {"name": role["name"]}
        ).scalar()
        if role_id is None:
            role_id = uuid.uuid4()
            conn.execute(
                sa.text(
                    "INSERT INTO roles (id, name, description, enabled, created_at, updated_at) "
                    "VALUES (:id, :name, :description, true, now(), now())"
                ),
                {"id": role_id, "name": role["name"], "description": role["description"]},
            )
        conn.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_code) "
                "VALUES (:role_id, :permission_code) ON CONFLICT DO NOTHING"
            ),
            [{"role_id": role_id, "permission_code": code} for code in role["permissions"]],
        )


def downgrade() -> None:
    # 仅回滚本迁移新增的结构；角色记录保留，避免破坏既有用户角色分配。
    op.drop_table("role_permissions")
    op.drop_table("permissions")
