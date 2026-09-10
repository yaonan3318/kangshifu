"""P2-1 search accuracy: document validity window and admin-maintained dictionary.

新增 documents.valid_from/valid_until（文档有效期）与 retrieval_dictionary_entries
（管理员维护的同义词/缩写/专有名词），并幂等写入需求示例词典。历史数据不受影响。
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_search_accuracy"
down_revision = "0019_evaluation_sets"
branch_labels = None
depends_on = None


DICTIONARY_SEED = [
    {"category": "SYNONYM", "term": "日报", "expansions": ["日报汇总", "工作记录", "周报"]},
    {"category": "SYNONYM", "term": "气泡", "expansions": ["气泡检测", "气泡识别", "bubble"]},
    {"category": "ABBREVIATION", "term": "k8s", "expansions": ["kubernetes", "容器编排"]},
]


def upgrade() -> None:
    op.add_column("documents", sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_documents_valid_from", "documents", ["valid_from"])
    op.create_index("ix_documents_valid_until", "documents", ["valid_until"])

    op.create_table(
        "retrieval_dictionary_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("term", sa.String(length=255), nullable=False),
        sa.Column("expansions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("category", "term", name="uq_retrieval_dictionary_category_term"),
    )
    op.create_index("ix_retrieval_dictionary_entries_category", "retrieval_dictionary_entries", ["category"])
    op.create_index("ix_retrieval_dictionary_entries_term", "retrieval_dictionary_entries", ["term"])
    op.create_index("ix_retrieval_dictionary_entries_enabled", "retrieval_dictionary_entries", ["enabled"])

    conn = op.get_bind()
    for entry in DICTIONARY_SEED:
        conn.execute(
            sa.text(
                "INSERT INTO retrieval_dictionary_entries (id, category, term, expansions, enabled, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :category, :term, CAST(:expansions AS jsonb), true, now(), now()) "
                "ON CONFLICT (category, term) DO NOTHING"
            ),
            {
                "category": entry["category"], "term": entry["term"],
                "expansions": json.dumps(entry["expansions"], ensure_ascii=False),
            },
        )


def downgrade() -> None:
    op.drop_index("ix_retrieval_dictionary_entries_enabled", table_name="retrieval_dictionary_entries")
    op.drop_index("ix_retrieval_dictionary_entries_term", table_name="retrieval_dictionary_entries")
    op.drop_index("ix_retrieval_dictionary_entries_category", table_name="retrieval_dictionary_entries")
    op.drop_table("retrieval_dictionary_entries")
    op.drop_index("ix_documents_valid_until", table_name="documents")
    op.drop_index("ix_documents_valid_from", table_name="documents")
    op.drop_column("documents", "valid_until")
    op.drop_column("documents", "valid_from")
