"""P2-1 retrieval log: persist recall and rerank ranks on answer sources.

在回答引用快照上记录召回排名与精排前后排名，便于在生产检索日志中追溯
“召回前后排名”和“Reranker 前后排名”。历史数据为空，不影响既有引用。
"""

import sqlalchemy as sa
from alembic import op

revision = "0026_retrieval_log_ranks"
down_revision = "0025_expected_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_message_sources", sa.Column("retrieval_rank", sa.Integer(), nullable=True))
    op.add_column("chat_message_sources", sa.Column("pre_rerank_rank", sa.Integer(), nullable=True))
    op.add_column("chat_message_sources", sa.Column("post_rerank_rank", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_message_sources", "post_rerank_rank")
    op.drop_column("chat_message_sources", "pre_rerank_rank")
    op.drop_column("chat_message_sources", "retrieval_rank")
