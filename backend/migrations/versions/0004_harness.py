"""Add durable Harness tasks, steps and approvals."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_harness"
down_revision = "0003_hybrid_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "harness_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("question", sa.Text(), nullable=False), sa.Column("context", sa.String(255), nullable=False),
        sa.Column("namespace", sa.String(255), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("model", sa.String(255), nullable=False), sa.Column("current_step", sa.Integer(), nullable=False),
        sa.Column("max_steps", sa.Integer(), nullable=False), sa.Column("history", postgresql.JSONB(), nullable=False),
        sa.Column("deployment_yaml", sa.Text()),
        sa.Column("final_answer", sa.Text()), sa.Column("error_code", sa.String(64)), sa.Column("error_message", sa.Text()),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_harness_tasks_status", "harness_tasks", ["status"])
    op.create_table(
        "harness_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("harness_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("tool_name", sa.String(128)), sa.Column("reason", sa.Text()),
        sa.Column("arguments", postgresql.JSONB(), nullable=False), sa.Column("result", postgresql.JSONB()),
        sa.Column("error_code", sa.String(64)), sa.Column("error_message", sa.Text()), sa.Column("duration_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_harness_steps_task_id", "harness_steps", ["task_id"])
    op.create_table(
        "harness_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("harness_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("harness_steps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("context", sa.String(255), nullable=False), sa.Column("namespace", sa.String(255), nullable=False),
        sa.Column("target", sa.String(512), nullable=False), sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column("yaml_content", sa.Text()), sa.Column("yaml_sha256", sa.String(64)), sa.Column("dry_run_output", sa.Text()),
        sa.Column("diff_output", sa.Text()), sa.Column("resource_versions", postgresql.JSONB(), nullable=False),
        sa.Column("actor", sa.String(128)), sa.Column("rejection_reason", sa.Text()), sa.Column("execution_result", postgresql.JSONB()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_harness_approvals_task_id", "harness_approvals", ["task_id"])
    op.create_index("ix_harness_approvals_status", "harness_approvals", ["status"])
    op.create_index("ix_harness_approvals_expires_at", "harness_approvals", ["expires_at"])


def downgrade() -> None:
    op.drop_table("harness_approvals")
    op.drop_table("harness_steps")
    op.drop_table("harness_tasks")
