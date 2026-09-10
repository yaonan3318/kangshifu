"""P2-4 lightweight Chatflow: fixed-canvas flows, published versions, assistant binding.

新增 chatflows / chatflow_versions 两张表，并给 assistants 增加 chatflow_id；
幂等写入一个默认流程并绑定默认助手。downgrade 回滚结构与种子数据。
"""

import json
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022_chatflow"
down_revision = "0021_assistant_roles"
branch_labels = None
depends_on = None

DEFAULT_ASSISTANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
DEFAULT_CHATFLOW_ID = uuid.UUID("00000000-0000-0000-0000-0000000000f1")

DEFAULT_GRAPH = {
    "nodes": [
        {"id": "start", "type": "start", "name": "开始", "enabled": True, "config": {}, "next": "classify"},
        {"id": "classify", "type": "question_classify", "name": "问题分类", "enabled": True, "config": {}, "next": "rewrite"},
        {"id": "rewrite", "type": "query_rewrite", "name": "上下文补全与改写", "enabled": True,
         "config": {"multi_query": True}, "next": "retrieval"},
        {"id": "retrieval", "type": "retrieval", "name": "知识库检索", "enabled": True, "config": {}, "next": "rerank"},
        {"id": "rerank", "type": "rerank", "name": "Reranker 精排", "enabled": True, "config": {}, "next": "confidence"},
        {"id": "confidence", "type": "condition", "name": "置信度判断", "enabled": True, "config": {
            "branches": [
                {"when": "sufficient", "next": "local_model"},
                {"when": "insufficient_and_deepseek", "next": "deepseek"},
                {"when": "ops", "next": "harness"},
            ],
            "default_next": "no_answer",
        }, "next": None},
        {"id": "local_model", "type": "local_model", "name": "本地千问", "enabled": True, "config": {}, "next": "answer_check"},
        {"id": "answer_check", "type": "answer_check", "name": "答案校验", "enabled": True, "config": {}, "next": "final_answer"},
        {"id": "deepseek", "type": "deepseek", "name": "DeepSeek 通用知识", "enabled": True, "config": {}, "next": "final_answer"},
        {"id": "harness", "type": "harness", "name": "Harness 运维", "enabled": True, "config": {}, "next": "final_answer"},
        {"id": "no_answer", "type": "no_answer", "name": "缺失知识提示", "enabled": True, "config": {}, "next": "final_answer"},
        {"id": "final_answer", "type": "final_answer", "name": "最终回答", "enabled": True, "config": {}, "next": None},
    ],
    "start_node_id": "start",
}


def upgrade() -> None:
    op.create_table(
        "chatflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("draft_graph", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("published_graph", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("published_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_chatflows_name"),
    )
    op.create_index("ix_chatflows_name", "chatflows", ["name"])
    op.create_index("ix_chatflows_enabled", "chatflows", ["enabled"])

    op.create_table(
        "chatflow_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("chatflow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chatflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("graph", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("chatflow_id", "version", name="uq_chatflow_versions_chatflow_version"),
    )
    op.create_index("ix_chatflow_versions_chatflow_id", "chatflow_versions", ["chatflow_id"])
    op.create_index("ix_chatflow_versions_created_at", "chatflow_versions", ["created_at"])

    op.add_column("assistants", sa.Column("chatflow_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_assistants_chatflow", "assistants", "chatflows",
        ["chatflow_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_assistants_chatflow_id", "assistants", ["chatflow_id"])

    conn = op.get_bind()
    graph_json = json.dumps(DEFAULT_GRAPH, ensure_ascii=False)
    conn.execute(
        sa.text(
            "INSERT INTO chatflows (id, name, description, draft_graph, published_graph, published_version, enabled, created_at, updated_at) "
            "VALUES (:id, :name, :description, CAST(:graph AS jsonb), CAST(:graph AS jsonb), 1, true, now(), now()) "
            "ON CONFLICT (name) DO NOTHING"
        ),
        {
            "id": DEFAULT_CHATFLOW_ID, "name": "默认流程",
            "description": "开始→分类→改写→检索→精排→置信度分支→本地/DeepSeek/Harness/缺失知识→最终回答",
            "graph": graph_json,
        },
    )
    # 写入首个版本快照。
    conn.execute(
        sa.text(
            "INSERT INTO chatflow_versions (id, chatflow_id, version, graph, note, created_at) "
            "SELECT gen_random_uuid(), :id, 1, CAST(:graph AS jsonb), '初始版本', now() "
            "WHERE NOT EXISTS (SELECT 1 FROM chatflow_versions WHERE chatflow_id = :id AND version = 1)"
        ),
        {"id": DEFAULT_CHATFLOW_ID, "graph": graph_json},
    )
    conn.execute(
        sa.text("UPDATE assistants SET chatflow_id = :chatflow WHERE id = :assistant"),
        {"chatflow": DEFAULT_CHATFLOW_ID, "assistant": DEFAULT_ASSISTANT_ID},
    )


def downgrade() -> None:
    op.drop_index("ix_assistants_chatflow_id", table_name="assistants")
    op.drop_constraint("fk_assistants_chatflow", "assistants", type_="foreignkey")
    op.drop_column("assistants", "chatflow_id")
    op.drop_index("ix_chatflow_versions_created_at", table_name="chatflow_versions")
    op.drop_index("ix_chatflow_versions_chatflow_id", table_name="chatflow_versions")
    op.drop_table("chatflow_versions")
    op.drop_index("ix_chatflows_enabled", table_name="chatflows")
    op.drop_index("ix_chatflows_name", table_name="chatflows")
    op.drop_table("chatflows")
