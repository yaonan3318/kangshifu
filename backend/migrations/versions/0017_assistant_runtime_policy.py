"""Move DeepSeek and Harness runtime choices into assistant configuration."""

import sqlalchemy as sa
from alembic import op


revision = "0017_assistant_runtime_policy"
down_revision = "0016_feedback_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assistants", sa.Column("deepseek_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("assistants", sa.Column("harness_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("assistants", sa.Column("harness_context", sa.String(length=255), nullable=True))
    op.add_column("assistants", sa.Column("harness_namespace", sa.String(length=255), nullable=False, server_default="default"))
    # 延续旧助手的“默认开启 DeepSeek”行为，升级后不会静默改变运行方式。
    op.execute("UPDATE assistants SET deepseek_enabled = default_deepseek_enabled")


def downgrade() -> None:
    op.drop_column("assistants", "harness_namespace")
    op.drop_column("assistants", "harness_context")
    op.drop_column("assistants", "harness_enabled")
    op.drop_column("assistants", "deepseek_enabled")
