"""P2-7A/B/C: feedback governance, safe ranking and re-verification.

- 扩展 answer_feedback：反馈类型、上下文快照、问题指纹与更新时间；
- 清理历史重复反馈并建立 (user_id, message_id) 唯一约束；
- 新增反馈历史、检索快照、处理工单、工单事件、聚合样本与复验记录表；
- 幂等写入反馈相关功能权限并授予默认管理角色。

所有新增列都可空或带 server_default；downgrade 只回滚本迁移新增结构，
不会删除既有 answer_feedback 业务数据。
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0029_feedback_governance"
down_revision = "0028_answer_jobs"
branch_labels = None
depends_on = None


FEEDBACK_PERMISSIONS = [
    {"code": "FEEDBACK_VIEW", "name": "反馈查看", "category": "operations", "sort_order": 130,
     "description": "查看反馈处理队列与详情"},
    {"code": "FEEDBACK_MANAGE", "name": "反馈处理", "category": "operations", "sort_order": 140,
     "description": "处理反馈、变更状态与记录结论"},
    {"code": "FEEDBACK_ASSIGN", "name": "反馈分配", "category": "operations", "sort_order": 150,
     "description": "分配反馈负责人与优先级"},
    {"code": "FEEDBACK_VERIFY", "name": "反馈复验", "category": "operations", "sort_order": 160,
     "description": "重新运行原问题并判定是否解决"},
    {"code": "FEEDBACK_STATISTICS", "name": "反馈统计", "category": "operations", "sort_order": 170,
     "description": "查看反馈运营统计与配置对比"},
]

# 默认角色 -> 新增反馈权限；系统管理员拥有全部反馈权限。
ROLE_GRANTS = {
    "系统管理员": [item["code"] for item in FEEDBACK_PERMISSIONS],
    "知识库管理员": ["FEEDBACK_VIEW", "FEEDBACK_MANAGE"],
}


def upgrade() -> None:
    _extend_answer_feedback()
    _create_governance_tables()
    _seed_permissions()


def _extend_answer_feedback() -> None:
    op.add_column("answer_feedback", sa.Column(
        "feedback_type", sa.String(16), nullable=False, server_default="UP"))
    op.add_column("answer_feedback", sa.Column(
        "chat_session_id", postgresql.UUID(as_uuid=True),
        sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True))
    op.add_column("answer_feedback", sa.Column(
        "assistant_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("answer_feedback", sa.Column("question_snapshot", sa.Text(), nullable=True))
    op.add_column("answer_feedback", sa.Column("answer_snapshot", sa.Text(), nullable=True))
    op.add_column("answer_feedback", sa.Column("knowledge_scope", sa.String(32), nullable=True))
    op.add_column("answer_feedback", sa.Column(
        "chunk_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("answer_feedback", sa.Column(
        "document_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("answer_feedback", sa.Column(
        "document_versions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("answer_feedback", sa.Column(
        "knowledge_base_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("answer_feedback", sa.Column(
        "retrieval_config_version_id", postgresql.UUID(as_uuid=True),
        sa.ForeignKey("retrieval_config_versions.id", ondelete="SET NULL"), nullable=True))
    op.add_column("answer_feedback", sa.Column("answer_model", sa.String(255), nullable=True))
    op.add_column("answer_feedback", sa.Column("answer_provider", sa.String(32), nullable=True))
    op.add_column("answer_feedback", sa.Column("query_fingerprint", sa.String(64), nullable=True))
    op.add_column("answer_feedback", sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))

    for name, column in (
        ("ix_answer_feedback_feedback_type", "feedback_type"),
        ("ix_answer_feedback_chat_session_id", "chat_session_id"),
        ("ix_answer_feedback_assistant_id", "assistant_id"),
        ("ix_answer_feedback_retrieval_config_version_id", "retrieval_config_version_id"),
        ("ix_answer_feedback_query_fingerprint", "query_fingerprint"),
    ):
        op.create_index(name, "answer_feedback", [column])

    # 历史反馈没有反馈类型字段：按原有极性回填，保证旧数据可读且统计正确。
    op.execute(
        "UPDATE answer_feedback SET feedback_type = "
        "CASE WHEN rating = 'UP' THEN 'UP' ELSE 'DOWN' END"
    )

    # 清理历史重复反馈：同一用户同一回答只保留最新一条（时间相同则保留 id 较大者）。
    op.execute(
        """
        DELETE FROM answer_feedback a
        USING answer_feedback b
        WHERE a.user_id IS NOT NULL
          AND a.user_id = b.user_id
          AND a.message_id = b.message_id
          AND (a.created_at < b.created_at
               OR (a.created_at = b.created_at AND a.id < b.id))
        """
    )
    op.create_unique_constraint(
        "uq_answer_feedback_user_message", "answer_feedback", ["user_id", "message_id"],
    )


def _create_governance_tables() -> None:
    op.create_table(
        "feedback_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("feedback_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("answer_feedback.id", ondelete="CASCADE"), nullable=False),
        sa.Column("change_type", sa.String(32), nullable=False),
        sa.Column("previous_rating", sa.String(16), nullable=True),
        sa.Column("new_rating", sa.String(16), nullable=True),
        sa.Column("previous_reasons", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("new_reasons", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("previous_comment", sa.Text(), nullable=True),
        sa.Column("new_comment", sa.Text(), nullable=True),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_feedback_history_feedback_id", "feedback_history", ["feedback_id"])
    op.create_index("ix_feedback_history_changed_by", "feedback_history", ["changed_by"])
    op.create_index("ix_feedback_history_changed_at", "feedback_history", ["changed_at"])

    op.create_table(
        "feedback_retrieval_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("feedback_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("answer_feedback.id", ondelete="CASCADE"), nullable=False),
        sa.Column("retrieval_config_version_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("retrieval_config_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chunks", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_feedback_retrieval_snapshots_feedback_id", "feedback_retrieval_snapshots", ["feedback_id"])

    op.create_table(
        "feedback_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("feedback_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("answer_feedback.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="NORMAL"),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("conclusion", sa.Text(), nullable=True),
        sa.Column("first_handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fix_document_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("fix_config_version_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("retrieval_config_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("last_verification_result", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("feedback_id", name="uq_feedback_cases_feedback_id"),
    )
    op.create_index("ix_feedback_cases_status", "feedback_cases", ["status"])
    op.create_index("ix_feedback_cases_priority", "feedback_cases", ["priority"])
    op.create_index("ix_feedback_cases_assignee_id", "feedback_cases", ["assignee_id"])
    op.create_index("ix_feedback_cases_feedback_id", "feedback_cases", ["feedback_id"])
    op.create_index("ix_feedback_cases_resolved_at", "feedback_cases", ["resolved_at"])
    op.create_index("ix_feedback_cases_created_at", "feedback_cases", ["created_at"])

    op.create_table(
        "feedback_case_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("feedback_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_feedback_case_events_case_id", "feedback_case_events", ["case_id"])
    op.create_index("ix_feedback_case_events_created_at", "feedback_case_events", ["created_at"])

    op.create_table(
        "feedback_aggregates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("query_fingerprint", sa.String(64), nullable=False),
        sa.Column("positive_users", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("negative_users", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("effective_users", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("admin_verified_positive", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("admin_verified_negative", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_feedback", sa.Float(), nullable=False, server_default="0"),
        sa.Column("bounded_feedback", sa.Float(), nullable=False, server_default="0"),
        sa.Column("feedback_boost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "knowledge_base_id", "chunk_id", "query_fingerprint",
            name="uq_feedback_aggregates_key",
        ),
    )
    op.create_index("ix_feedback_aggregates_knowledge_base_id", "feedback_aggregates", ["knowledge_base_id"])
    op.create_index("ix_feedback_aggregates_chunk_id", "feedback_aggregates", ["chunk_id"])
    op.create_index("ix_feedback_aggregates_query_fingerprint", "feedback_aggregates", ["query_fingerprint"])

    op.create_table(
        "feedback_verification_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("feedback_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feedback_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("answer_feedback.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="NOT_RUN"),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("before_answer", sa.Text(), nullable=True),
        sa.Column("before_sources", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("before_config_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("after_answer", sa.Text(), nullable=True),
        sa.Column("after_sources", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("after_config_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("after_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("base_score", sa.Float(), nullable=True),
        sa.Column("final_score", sa.Float(), nullable=True),
        sa.Column("no_answer", sa.Boolean(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("admin_conclusion", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_feedback_verification_runs_case_id", "feedback_verification_runs", ["case_id"])
    op.create_index("ix_feedback_verification_runs_feedback_id", "feedback_verification_runs", ["feedback_id"])
    op.create_index("ix_feedback_verification_runs_status", "feedback_verification_runs", ["status"])


def _seed_permissions() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO permissions (code, name, description, category, sort_order) "
            "VALUES (:code, :name, :description, :category, :sort_order) "
            "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, "
            "description = EXCLUDED.description, category = EXCLUDED.category, "
            "sort_order = EXCLUDED.sort_order"
        ),
        FEEDBACK_PERMISSIONS,
    )
    for role_name, codes in ROLE_GRANTS.items():
        role_id = conn.execute(
            sa.text("SELECT id FROM roles WHERE name = :name"), {"name": role_name}
        ).scalar()
        if role_id is None:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_code) "
                "VALUES (:role_id, :permission_code) ON CONFLICT DO NOTHING"
            ),
            [{"role_id": role_id, "permission_code": code} for code in codes],
        )


def downgrade() -> None:
    # 先删新增结构，再移除 answer_feedback 扩展列；保留业务数据。
    op.drop_table("feedback_verification_runs")
    op.drop_table("feedback_aggregates")
    op.drop_table("feedback_case_events")
    op.drop_table("feedback_cases")
    op.drop_table("feedback_retrieval_snapshots")
    op.drop_table("feedback_history")

    op.drop_constraint("uq_answer_feedback_user_message", "answer_feedback", type_="unique")
    for name in (
        "ix_answer_feedback_query_fingerprint",
        "ix_answer_feedback_retrieval_config_version_id",
        "ix_answer_feedback_assistant_id",
        "ix_answer_feedback_chat_session_id",
        "ix_answer_feedback_feedback_type",
    ):
        op.drop_index(name, table_name="answer_feedback")
    for column in (
        "updated_at", "query_fingerprint", "answer_provider", "answer_model",
        "retrieval_config_version_id", "knowledge_base_ids", "document_versions",
        "document_ids", "chunk_ids", "knowledge_scope", "answer_snapshot",
        "question_snapshot", "assistant_id", "chat_session_id", "feedback_type",
    ):
        op.drop_column("answer_feedback", column)

    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_code IN :codes").bindparams(
            sa.bindparam("codes", expanding=True)
        ),
        {"codes": [item["code"] for item in FEEDBACK_PERMISSIONS]},
    )
    conn.execute(
        sa.text("DELETE FROM permissions WHERE code IN :codes").bindparams(
            sa.bindparam("codes", expanding=True)
        ),
        {"codes": [item["code"] for item in FEEDBACK_PERMISSIONS]},
    )
