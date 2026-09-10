"""Evaluation sets and versioned retrieval configs for P2-0 quality baseline.

新增评测集、检索配置版本，并扩展标准问题与运行记录；把历史用例归入默认评测集，
同时写入一个默认检索配置版本。所有历史数据保留，不删除、不清空。
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019_evaluation_sets"
down_revision = "0018_function_rbac"
branch_labels = None
depends_on = None

# 与 app/services/retrieval_config.py 的默认值保持一致（冻结快照）。
DEFAULT_CONFIG = {
    "keyword_limit": 30,
    "vector_limit": 30,
    "rrf_k": 60,
    "keyword_weight": 1.0,
    "vector_weight": 1.0,
    "rerank_enabled": False,
    "rerank_model": "BAAI/bge-reranker-v2-m3",
    "rerank_candidate_limit": 20,
    "similarity_threshold": 0.55,
    "min_evidence_score": 0.35,
    "per_document_limit": 3,
    "final_limit": 6,
    "query_rewrite_synonyms": "k8s|kubernetes|容器编排;气泡项目|气泡检测|bubble;日报|工作记录|周报",
}


def upgrade() -> None:
    op.create_table(
        "evaluation_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_evaluation_sets_knowledge_base_id", "evaluation_sets", ["knowledge_base_id"])
    op.create_index("ix_evaluation_sets_enabled", "evaluation_sets", ["enabled"])

    op.create_table(
        "retrieval_config_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_retrieval_config_versions_is_default", "retrieval_config_versions", ["is_default"])

    op.add_column("retrieval_test_cases", sa.Column("evaluation_set_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("retrieval_test_cases", sa.Column("must_cite_document_ids", postgresql.JSONB(),
                  nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("retrieval_test_cases", sa.Column("forbidden_document_ids", postgresql.JSONB(),
                  nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("retrieval_test_cases", sa.Column("expected_answer_keypoints", postgresql.JSONB(),
                  nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.create_foreign_key(
        "fk_retrieval_test_cases_evaluation_set", "retrieval_test_cases", "evaluation_sets",
        ["evaluation_set_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index("ix_retrieval_test_cases_evaluation_set_id", "retrieval_test_cases", ["evaluation_set_id"])

    op.add_column("retrieval_test_runs", sa.Column("evaluation_set_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("retrieval_test_runs", sa.Column("config_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("retrieval_test_runs", sa.Column("config_snapshot", postgresql.JSONB(),
                  nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.create_foreign_key(
        "fk_retrieval_test_runs_evaluation_set", "retrieval_test_runs", "evaluation_sets",
        ["evaluation_set_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_retrieval_test_runs_config_version", "retrieval_test_runs", "retrieval_config_versions",
        ["config_version_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_retrieval_test_runs_evaluation_set_id", "retrieval_test_runs", ["evaluation_set_id"])
    op.create_index("ix_retrieval_test_runs_config_version_id", "retrieval_test_runs", ["config_version_id"])

    conn = op.get_bind()
    # 默认评测集：把历史用例与运行记录归入其中，避免数据丢失。
    default_set_id = conn.execute(sa.text("SELECT gen_random_uuid()")).scalar()
    conn.execute(
        sa.text(
            "INSERT INTO evaluation_sets (id, name, description, enabled, created_at, updated_at) "
            "VALUES (:id, :name, :description, true, now(), now())"
        ),
        {"id": default_set_id, "name": "默认评测集", "description": "迁移自动创建，包含历史标准问题"},
    )
    conn.execute(
        sa.text("UPDATE retrieval_test_cases SET evaluation_set_id = :id WHERE evaluation_set_id IS NULL"),
        {"id": default_set_id},
    )
    conn.execute(
        sa.text("UPDATE retrieval_test_runs SET evaluation_set_id = :id WHERE evaluation_set_id IS NULL"),
        {"id": default_set_id},
    )

    # 默认检索配置版本（快照当前默认值）。
    config_id = conn.execute(sa.text("SELECT gen_random_uuid()")).scalar()
    conn.execute(
        sa.text(
            "INSERT INTO retrieval_config_versions (id, name, description, config, is_default, created_at, updated_at) "
            "VALUES (:id, :name, :description, CAST(:config AS jsonb), true, now(), now())"
        ),
        {
            "id": config_id, "name": "默认配置 v1",
            "description": "P2-0 基线：关键词/向量各 30，RRF k=60，精排关闭",
            "config": json.dumps(DEFAULT_CONFIG, ensure_ascii=False),
        },
    )


def downgrade() -> None:
    op.drop_index("ix_retrieval_test_runs_config_version_id", table_name="retrieval_test_runs")
    op.drop_index("ix_retrieval_test_runs_evaluation_set_id", table_name="retrieval_test_runs")
    op.drop_constraint("fk_retrieval_test_runs_config_version", "retrieval_test_runs", type_="foreignkey")
    op.drop_constraint("fk_retrieval_test_runs_evaluation_set", "retrieval_test_runs", type_="foreignkey")
    op.drop_column("retrieval_test_runs", "config_snapshot")
    op.drop_column("retrieval_test_runs", "config_version_id")
    op.drop_column("retrieval_test_runs", "evaluation_set_id")
    op.drop_index("ix_retrieval_test_cases_evaluation_set_id", table_name="retrieval_test_cases")
    op.drop_constraint("fk_retrieval_test_cases_evaluation_set", "retrieval_test_cases", type_="foreignkey")
    op.drop_column("retrieval_test_cases", "expected_answer_keypoints")
    op.drop_column("retrieval_test_cases", "forbidden_document_ids")
    op.drop_column("retrieval_test_cases", "must_cite_document_ids")
    op.drop_column("retrieval_test_cases", "evaluation_set_id")
    op.drop_index("ix_retrieval_config_versions_is_default", table_name="retrieval_config_versions")
    op.drop_table("retrieval_config_versions")
    op.drop_index("ix_evaluation_sets_enabled", table_name="evaluation_sets")
    op.drop_index("ix_evaluation_sets_knowledge_base_id", table_name="evaluation_sets")
    op.drop_table("evaluation_sets")
