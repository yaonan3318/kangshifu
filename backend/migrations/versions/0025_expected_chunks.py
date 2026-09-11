"""P2-0 quality baseline: expected chunk ground truth for chunk-level recall.

为评测标准问题增加期望片段（expected_chunk_ids），用于计算真正的“正确片段召回率”，
而不是用命中文档数冒充。历史用例默认空数组，不影响既有数据。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025_expected_chunks"
down_revision = "0024_document_understanding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "retrieval_test_cases",
        sa.Column(
            "expected_chunk_ids", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("retrieval_test_cases", "expected_chunk_ids")
