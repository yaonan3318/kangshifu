"""Add configurable assistants and attach default assistant to chat sessions."""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0009_assistants"
down_revision = "0008_answer_metrics"
branch_labels = None
depends_on = None

DEFAULT_ASSISTANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

DEFAULT_SYSTEM_PROMPT = (
    "你是康师傅公司的综合知识助手。只能把提供的内部资料作为公司事实依据，"
    "用专业、简洁、有引用的中文回答；没有可靠资料时明确说明，不编造公司结论。"
)


def upgrade() -> None:
    op.create_table(
        "assistants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("avatar", sa.String(16), nullable=False, server_default="康"),
        sa.Column("welcome_message", sa.Text()),
        sa.Column("system_prompt", sa.Text()),
        sa.Column("model_provider", sa.String(32), nullable=False, server_default="ollama"),
        sa.Column("model_name", sa.String(255)),
        sa.Column("use_deepseek_allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_deepseek_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("retrieval_limit", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("recommended_questions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_assistants_name"),
    )
    op.create_index("ix_assistants_name", "assistants", ["name"])
    op.create_index("ix_assistants_enabled", "assistants", ["enabled"])

    op.create_table(
        "assistant_knowledge_bases",
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assistants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_assistant_knowledge_bases_kb", "assistant_knowledge_bases", ["knowledge_base_id"])

    op.execute(
        sa.text(
            "INSERT INTO assistants (id, name, description, avatar, welcome_message, system_prompt, "
            "model_provider, model_name, use_deepseek_allowed, default_deepseek_enabled, retrieval_limit, "
            "temperature, recommended_questions, enabled) VALUES "
            "(:id, '康师傅公司助手', '公司综合知识助手，覆盖技术、人事、产品与运营资料', '康', "
            "'你好，我是康师傅公司助手。我可以基于公司内部资料回答你的问题。', :system_prompt, "
            "'ollama', 'qwen3:8b', true, false, 6, 0.2, "
            "'[\"公司目前采用什么气泡检测方案？\",\"Go 服务如何部署到 Kubernetes？\",\"最新的休假和考勤制度是什么？\",\"报销流程需要提交哪些材料？\"]'::jsonb, true)"
        ).bindparams(sa.bindparam("id", value=DEFAULT_ASSISTANT_ID, type_=postgresql.UUID(as_uuid=True)),
                     sa.bindparam("system_prompt", value=DEFAULT_SYSTEM_PROMPT, type_=sa.Text))
    )

    # 历史会话没有指定助手时绑定到默认助手，并补上外键约束。
    op.execute(
        sa.text("UPDATE chat_sessions SET assistant_id = :id WHERE assistant_id IS NULL").bindparams(
            sa.bindparam("id", value=DEFAULT_ASSISTANT_ID, type_=postgresql.UUID(as_uuid=True))
        )
    )
    op.create_foreign_key(
        "fk_chat_sessions_assistant", "chat_sessions", "assistants",
        ["assistant_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_chat_sessions_assistant", "chat_sessions", type_="foreignkey")
    op.drop_index("ix_assistant_knowledge_bases_kb", table_name="assistant_knowledge_bases")
    op.drop_table("assistant_knowledge_bases")
    op.drop_table("assistants")
