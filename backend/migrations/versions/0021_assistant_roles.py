"""P2-3 assistant roles: answer template, internet flag, no-answer policy and presets.

新增助手角色字段并幂等预置六个角色助手；默认助手重命名为“康师傅综合助手”。
不删除任何现有助手或会话，downgrade 仅回滚新增结构与预置数据。
"""

import json
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021_assistant_roles"
down_revision = "0020_search_accuracy"
branch_labels = None
depends_on = None

DEFAULT_ASSISTANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

DEFAULT_SYSTEM_PROMPT = (
    "你是康师傅公司的综合知识助手。只能把提供的内部资料作为公司事实依据，"
    "用专业、简洁、有引用的中文回答；没有可靠资料时明确说明，不编造公司结论。"
)

PRESET_ASSISTANTS = [
    {
        "name": "康师傅综合助手", "avatar": "康",
        "description": "公司综合知识助手，覆盖技术、人事、产品与运营资料",
        "welcome_message": "你好，我是康师傅综合助手，可以基于公司内部资料回答你的问题。",
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "answer_template": "AUTO", "no_answer_policy": "SUGGEST",
        "capabilities": ["基于公司内部资料回答问题", "按主题整理答案并标注引用", "在允许时使用通用知识补充"],
        "limitations": ["只依据你有权访问的资料", "没有依据时不编造公司结论", "不会执行运维操作（除非管理员授权）"],
        "recommended_questions": [
            "公司目前采用什么气泡检测方案？", "Go 服务如何部署到 Kubernetes？",
            "最新的休假和考勤制度是什么？", "报销流程需要提交哪些材料？",
        ],
    },
    {
        "name": "人事制度助手", "avatar": "人",
        "description": "解读人事制度、考勤休假与办理流程",
        "welcome_message": "你好，我是人事制度助手，可以帮你解读公司人事制度与办理流程。",
        "system_prompt": "你是公司人事制度助手。只能依据公司人事制度资料回答，说明适用范围与办理步骤，不提供法律意见。",
        "answer_template": "POLICY", "no_answer_policy": "SUGGEST",
        "capabilities": ["解读人事制度与办理流程", "说明适用范围与注意事项"],
        "limitations": ["不提供法律意见", "不访问技术资料"],
        "recommended_questions": ["年假如何计算？", "请假需要哪些审批？", "报销流程是什么？", "加班如何调休？"],
    },
    {
        "name": "技术研发助手", "avatar": "技",
        "description": "面向研发的技术文档助手",
        "welcome_message": "你好，我是技术研发助手，可以基于技术文档给出实施步骤与风险提示。",
        "system_prompt": "你是公司技术研发助手。只能依据技术资料回答，给出可执行的步骤与命令，并提示风险。",
        "answer_template": "TECHNICAL", "no_answer_policy": "SUGGEST",
        "capabilities": ["结合技术文档给出实施步骤与命令", "提示常见风险"],
        "limitations": ["命令需人工确认后执行", "不访问人事资料"],
        "recommended_questions": ["服务如何部署到 K8s？", "如何排查接口报错？", "数据库连接池怎么配置？", "模型训练流程是什么？"],
    },
    {
        "name": "产品资料助手", "avatar": "产",
        "description": "汇总产品功能与版本资料",
        "welcome_message": "你好，我是产品资料助手，可以汇总产品功能与版本要点。",
        "system_prompt": "你是公司产品资料助手。只能依据产品资料回答，按主题归类并给出关键结论与引用。",
        "answer_template": "SUMMARY", "no_answer_policy": "SUGGEST",
        "capabilities": ["汇总产品资料与版本要点"],
        "limitations": ["不包含未归档的草稿资料"],
        "recommended_questions": ["产品有哪些核心功能？", "版本更新了什么？", "主要竞品差异是什么？"],
    },
    {
        "name": "运维助手", "avatar": "运",
        "description": "结合运维文档回答问题并执行白名单运维操作",
        "welcome_message": "你好，我是运维助手，可以在管理员确认后执行白名单运维操作。",
        "system_prompt": "你是公司运维助手。只能依据运维资料回答；涉及写操作时必须说明风险并等待人工确认。",
        "answer_template": "TECHNICAL", "no_answer_policy": "SUGGEST",
        "capabilities": ["结合运维文档回答问题", "在管理员确认后执行白名单运维操作"],
        "limitations": ["写操作必须逐次人工确认", "不能绕过权限与审计"],
        "recommended_questions": ["如何重启 deployment？", "查看命名空间资源", "扩容需要哪些审批？"],
    },
    {
        "name": "项目进度助手", "avatar": "项",
        "description": "按时间线汇总项目进展与阻塞",
        "welcome_message": "你好，我是项目进度助手，可以按时间线汇总项目状态与阻塞问题。",
        "system_prompt": "你是公司项目进度助手。只能依据周报与进展资料回答，按时间线组织，说明当前状态、阻塞与下一步。",
        "answer_template": "PROGRESS", "no_answer_policy": "SUGGEST",
        "capabilities": ["按时间线汇总项目状态与阻塞"],
        "limitations": ["只反映已归档的周报/进展资料"],
        "recommended_questions": ["气泡项目当前进展？", "有哪些阻塞问题？", "下一步计划是什么？"],
    },
]


def upgrade() -> None:
    op.add_column("assistants", sa.Column("answer_template", sa.String(32), nullable=False, server_default="AUTO"))
    op.add_column("assistants", sa.Column("internet_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("assistants", sa.Column("no_answer_policy", sa.String(16), nullable=False, server_default="SUGGEST"))
    op.add_column("assistants", sa.Column("capabilities", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("assistants", sa.Column("limitations", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))

    conn = op.get_bind()
    # 默认助手升级为“康师傅综合助手”，保留原 ID 与会话绑定。
    default = PRESET_ASSISTANTS[0]
    conn.execute(
        sa.text(
            "UPDATE assistants SET name = :name, avatar = :avatar, description = :description, "
            "welcome_message = :welcome_message, system_prompt = :system_prompt, answer_template = :answer_template, "
            "no_answer_policy = :no_answer_policy, capabilities = CAST(:capabilities AS jsonb), "
            "limitations = CAST(:limitations AS jsonb), recommended_questions = CAST(:questions AS jsonb) "
            "WHERE id = :id"
        ),
        {
            "id": DEFAULT_ASSISTANT_ID, "name": default["name"], "avatar": default["avatar"],
            "description": default["description"], "welcome_message": default["welcome_message"],
            "system_prompt": default["system_prompt"], "answer_template": default["answer_template"],
            "no_answer_policy": default["no_answer_policy"],
            "capabilities": json.dumps(default["capabilities"], ensure_ascii=False),
            "limitations": json.dumps(default["limitations"], ensure_ascii=False),
            "questions": json.dumps(default["recommended_questions"], ensure_ascii=False),
        },
    )

    for preset in PRESET_ASSISTANTS[1:]:
        conn.execute(
            sa.text(
                "INSERT INTO assistants (id, name, description, avatar, welcome_message, system_prompt, "
                "model_provider, model_name, use_deepseek_allowed, default_deepseek_enabled, deepseek_enabled, "
                "harness_enabled, harness_namespace, retrieval_limit, temperature, recommended_questions, "
                "answer_template, internet_enabled, no_answer_policy, capabilities, limitations, enabled) VALUES "
                "(gen_random_uuid(), :name, :description, :avatar, :welcome_message, :system_prompt, "
                "'ollama', NULL, true, false, false, :harness_enabled, 'default', 6, 0.2, "
                "CAST(:questions AS jsonb), :answer_template, false, :no_answer_policy, "
                "CAST(:capabilities AS jsonb), CAST(:limitations AS jsonb), true) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {
                "name": preset["name"], "description": preset["description"], "avatar": preset["avatar"],
                "welcome_message": preset["welcome_message"], "system_prompt": preset["system_prompt"],
                "harness_enabled": preset["name"] == "运维助手",
                "questions": json.dumps(preset["recommended_questions"], ensure_ascii=False),
                "answer_template": preset["answer_template"], "no_answer_policy": preset["no_answer_policy"],
                "capabilities": json.dumps(preset["capabilities"], ensure_ascii=False),
                "limitations": json.dumps(preset["limitations"], ensure_ascii=False),
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    for preset in PRESET_ASSISTANTS[1:]:
        conn.execute(sa.text("DELETE FROM assistants WHERE name = :name"), {"name": preset["name"]})
    conn.execute(
        sa.text("UPDATE assistants SET name = '康师傅公司助手' WHERE id = :id"),
        {"id": DEFAULT_ASSISTANT_ID},
    )
    op.drop_column("assistants", "limitations")
    op.drop_column("assistants", "capabilities")
    op.drop_column("assistants", "no_answer_policy")
    op.drop_column("assistants", "internet_enabled")
    op.drop_column("assistants", "answer_template")
