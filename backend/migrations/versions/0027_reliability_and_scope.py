"""P2-2/P2-3: persist citation document version and assistant knowledge-base scope flag.

- chat_message_sources.document_version：历史引用可判断“版本已更新”。
- assistants.allow_all_knowledge_bases：明确“全部知识库”语义；专项助手未绑定知识库时
  不再默认放大到全部知识库。默认综合助手显式设为全部知识库。
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_reliability_and_scope"
down_revision = "0026_retrieval_log_ranks"
branch_labels = None
depends_on = None

DEFAULT_ASSISTANT_ID = "00000000-0000-0000-0000-000000000002"


def upgrade() -> None:
    op.add_column("chat_message_sources", sa.Column("document_version", sa.Integer(), nullable=True))
    op.add_column("assistants", sa.Column(
        "allow_all_knowledge_bases", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    # 默认“康师傅综合助手”显式拥有全部启用知识库范围。
    op.execute(
        sa.text("UPDATE assistants SET allow_all_knowledge_bases = true WHERE id = CAST(:id AS uuid)")
        .bindparams(id=DEFAULT_ASSISTANT_ID)
    )


def downgrade() -> None:
    op.drop_column("assistants", "allow_all_knowledge_bases")
    op.drop_column("chat_message_sources", "document_version")
