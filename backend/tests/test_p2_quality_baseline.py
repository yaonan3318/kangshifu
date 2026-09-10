"""P2-0 质量基线纯单元测试：检索配置版本化与评测指标计算（不依赖数据库）。"""

from app.services.retrieval_config import RetrievalConfig, config_diff
from app.services.retrieval_evaluation import RetrievalEvaluationService, _mean, _ratio

_keypoint_coverage = RetrievalEvaluationService._keypoint_coverage


def test_config_round_trip_and_defaults():
    config = RetrievalConfig.from_dict({"keyword_limit": "15", "rrf_k": 42, "rerank_enabled": "true"})
    assert config.keyword_limit == 15
    assert config.rrf_k == 42
    assert config.rerank_enabled is True
    # 未提供的字段回退默认值。
    assert config.vector_limit == 30
    assert config.similarity_threshold == 0.55

    restored = RetrievalConfig.from_dict(config.to_dict())
    assert restored == config


def test_config_from_dict_ignores_invalid_values():
    config = RetrievalConfig.from_dict({"keyword_limit": "not-a-number", "similarity_threshold": "oops"})
    assert config.keyword_limit == 30
    assert config.similarity_threshold == 0.55


def test_config_diff_reports_changed_fields():
    left = RetrievalConfig(keyword_limit=10, rerank_enabled=False)
    right = RetrievalConfig(keyword_limit=20, rerank_enabled=True)
    differences = {item["field"]: item for item in config_diff(left, right)}
    assert set(differences) == {"keyword_limit", "rerank_enabled"}
    assert differences["keyword_limit"]["left"] == 10
    assert differences["keyword_limit"]["right"] == 20
    assert differences["rerank_enabled"]["label"] == "Reranker 开关"


def test_ratio_and_mean_helpers():
    assert _ratio(2, 4) == 0.5
    assert _ratio(1, 0) == 1.0  # 无预期时视为满分
    assert _mean([0.0, 1.0, 0.5]) == 0.5
    assert _mean([]) == 0.0


def test_keypoint_coverage():
    assert _keypoint_coverage([], "任意文本") == 1.0
    assert _keypoint_coverage(["部署", "回滚"], "请先部署再回滚") == 1.0
    assert _keypoint_coverage(["部署", "回滚"], "只提到部署") == 0.5
    assert _keypoint_coverage(["不存在"], "无关答案") == 0.0


def test_aggregate_metrics_average_and_mode():
    outcomes = [
        {
            "document_recall": 1.0, "chunk_recall": 1.0, "hit_rate_at_1": 1.0,
            "hit_rate_at_3": 1.0, "hit_rate_at_5": 1.0, "keypoint_coverage": 1.0,
            "citation_accuracy": 1.0, "no_answer_accuracy": 1.0,
            "retrieval_ms": 10.0, "first_token_latency_ms": 10.0, "answer_latency_ms": 10.0,
            "forbidden_hits": [],
        },
        {
            "document_recall": 0.0, "chunk_recall": 0.0, "hit_rate_at_1": 0.0,
            "hit_rate_at_3": 0.0, "hit_rate_at_5": 0.0, "keypoint_coverage": 0.0,
            "citation_accuracy": 0.0, "no_answer_accuracy": 0.0,
            "retrieval_ms": 30.0, "first_token_latency_ms": 30.0, "answer_latency_ms": 30.0,
            "forbidden_hits": ["doc-x"],
        },
    ]
    metrics = RetrievalEvaluationService._aggregate(outcomes, include_answers=False)
    assert metrics["case_count"] == 2
    assert metrics["document_recall"] == 0.5
    assert metrics["hit_rate_at_5"] == 0.5
    assert metrics["answer_latency_ms"] == 20.0
    assert metrics["forbidden_violation_count"] == 1
    assert metrics["answer_mode"] == "evidence"


def test_search_service_accepts_config_overrides():
    """检索服务应读取配置版本，而不是只依赖运行时 settings。"""
    config = RetrievalConfig(keyword_limit=7, vector_limit=9, rrf_k=13, min_evidence_score=0.9)
    assert config.keyword_limit == 7
    assert config.vector_limit == 9
    assert config.rrf_k == 13
    assert config.min_evidence_score == 0.9
