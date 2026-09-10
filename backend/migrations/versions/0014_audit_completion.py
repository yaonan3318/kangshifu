"""Audit completion: success flag, error code and request correlation id."""

import sqlalchemy as sa
from alembic import op


revision = "0014_audit_completion"
down_revision = "0013_identity_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 历史审计记录默认视为成功，避免升级后筛选“成功”时丢失旧记录。
    op.add_column(
        "audit_logs",
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("audit_logs", sa.Column("error_code", sa.String(64)))
    op.add_column("audit_logs", sa.Column("request_id", sa.String(64)))
    op.create_index("ix_audit_logs_success", "audit_logs", ["success"])
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_success", table_name="audit_logs")
    op.drop_column("audit_logs", "request_id")
    op.drop_column("audit_logs", "error_code")
    op.drop_column("audit_logs", "success")
