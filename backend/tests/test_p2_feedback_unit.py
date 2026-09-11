"""P2-7 反馈治理与安全排序纯单元测试（不依赖数据库）。

覆盖需求：
- 查询指纹归一化；
- 不同用户门槛、单用户去重、权重上下限；
- 管理员确认权重仍受总上限约束；
- 检索配置反馈参数的后端强制校验；
- 反馈权限码注册；
- 关键实现约束（唯一约束、乘法微调、相关性保护、管理接口鉴权）。
"""

from pathlib import Path

import pytest

from app.errors import AppError
from app.services import rbac
from app.services.feedback_ranking import compute_feedback_adjustment, query_fingerprint
from app.services.retrieval_config import RetrievalConfig, validate_feedback_config

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent


def source(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


# ---------------------------------------------------------------- 查询指纹

def test_fingerprint_normalizes_whitespace_and_punctuation():
    assert query_fingerprint("  日报 怎么 写？ ") == query_fingerprint("日报怎么写")
    assert query_fingerprint("日报") != query_fingerprint("周报")
    assert query_fingerprint(None) == query_fingerprint("")


# ---------------------------------------------------------------- 样本门槛与去重

def test_four_users_do_not_trigger_boost():
    raw, bounded, boost, applied, reason = compute_feedback_adjustment(
        positive_users=4, negative_users=0, min_distinct_users=5,
    )
    assert (raw, bounded, boost, applied) == (0.0, 0.0, 0.0, False)
    assert reason == "insufficient_distinct_users"


def test_five_users_produce_small_positive_boost():
    _, _, boost, applied, _ = compute_feedback_adjustment(
        positive_users=5, negative_users=0, min_distinct_users=5, max_positive_boost=0.08,
    )
    assert applied is True
    assert boost == pytest.approx(0.08)


def test_single_user_repeated_submission_counts_once():
    # 去重后只有一个不同用户，低于门槛，不生效。
    _, _, boost, applied, _ = compute_feedback_adjustment(
        positive_users=1, negative_users=0, min_distinct_users=5,
    )
    assert boost == 0.0
    assert applied is False


def test_positive_boost_never_exceeds_eight_percent():
    _, _, boost, _, _ = compute_feedback_adjustment(
        positive_users=50, negative_users=0, min_distinct_users=5, max_positive_boost=0.08,
    )
    assert boost <= 0.08


def test_negative_penalty_never_exceeds_ten_percent():
    _, _, boost, _, _ = compute_feedback_adjustment(
        positive_users=0, negative_users=50, min_distinct_users=5, max_negative_penalty=0.10,
    )
    assert boost >= -0.10


def test_admin_verified_weight_increases_but_stays_capped():
    plain = compute_feedback_adjustment(
        positive_users=5, negative_users=5, min_distinct_users=5, max_positive_boost=0.08,
    )[2]
    verified = compute_feedback_adjustment(
        positive_users=5, negative_users=5, admin_verified_positive=5,
        min_distinct_users=5, max_positive_boost=0.08, admin_verified_weight=1.5,
    )[2]
    assert verified > plain
    assert verified <= 0.08


def test_no_samples_reason():
    _, _, boost, applied, reason = compute_feedback_adjustment(positive_users=0, negative_users=0)
    assert boost == 0.0 and applied is False
    assert reason == "no_samples"


# ---------------------------------------------------------------- 配置边界

def test_validate_feedback_config_accepts_defaults():
    validate_feedback_config(RetrievalConfig())


@pytest.mark.parametrize("field,value", [
    ("feedback_max_positive_boost", 0.5),
    ("feedback_max_negative_penalty", 0.9),
    ("feedback_admin_verified_weight", 5.0),
    ("feedback_min_distinct_users", 2),
    ("feedback_valid_days", -1),
])
def test_validate_feedback_config_rejects_out_of_range(field, value):
    with pytest.raises(AppError) as exc:
        validate_feedback_config(RetrievalConfig(**{field: value}))
    assert exc.value.code == "INVALID_RETRIEVAL_CONFIG"


def test_config_roundtrip_keeps_feedback_fields():
    config = RetrievalConfig(feedback_ranking_enabled=True, feedback_min_distinct_users=7)
    restored = RetrievalConfig.from_dict(config.to_dict())
    assert restored.feedback_ranking_enabled is True
    assert restored.feedback_min_distinct_users == 7


# ---------------------------------------------------------------- 权限

def test_feedback_permission_codes_registered():
    for code in ("FEEDBACK_VIEW", "FEEDBACK_MANAGE", "FEEDBACK_ASSIGN",
                 "FEEDBACK_VERIFY", "FEEDBACK_STATISTICS"):
        assert code in rbac.PERMISSION_CODES


# ---------------------------------------------------------------- 实现约束

def test_answer_feedback_has_unique_constraint_and_snapshot_fields():
    model = source("backend/app/models/feedback.py")
    assert "uq_answer_feedback_user_message" in model
    for field in ("question_snapshot", "answer_snapshot", "chunk_ids", "knowledge_base_ids",
                  "retrieval_config_version_id", "query_fingerprint"):
        assert field in model


def test_ranking_uses_multiplicative_bounded_adjustment():
    ranking = source("backend/app/services/feedback_ranking.py")
    assert "knowledge_base_id" in ranking and "query_fingerprint" in ranking
    search = source("backend/app/services/search.py")
    # 乘法微调 + 相关性保护，且证据阈值仍使用未叠加反馈的基础分。
    assert "(1.0 + adjustment.boost)" in search
    assert "base_relevance_below_threshold" in search
    assert "if item.final_score < self.config.min_evidence_score" in search


def test_admin_feedback_endpoints_require_permissions():
    api = source("backend/app/api/feedback_admin.py")
    for code in ("FEEDBACK_VIEW", "FEEDBACK_MANAGE", "FEEDBACK_ASSIGN",
                 "FEEDBACK_VERIFY", "FEEDBACK_STATISTICS"):
        assert f"require_permission(current_user(request), {code})" in api
    assert "/cases/{case_id}/verify" in api
    assert "/config-comparison" in api


def test_feedback_case_status_transitions_are_validated():
    service = source("backend/app/services/feedback.py")
    assert "ALLOWED_TRANSITIONS" in service
    assert "INVALID_FEEDBACK_TRANSITION" in service


def test_document_change_triggers_reverify():
    trigger = source("backend/app/services/feedback_triggers.py")
    assert "mark_wait_verify_for_documents" in trigger
    documents = source("backend/app/services/documents.py")
    assert "trigger_reverify" in documents
    chunks = source("backend/app/services/chunks.py")
    assert "trigger_reverify" in chunks
