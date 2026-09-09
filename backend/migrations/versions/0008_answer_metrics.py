"""Add answer metrics JSONB to chat messages for performance observability."""

import sqlalchemy as sa
from alembic import op


revision = "0008_answer_metrics"
down_revision = "0007_chat_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("metrics", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "metrics")
