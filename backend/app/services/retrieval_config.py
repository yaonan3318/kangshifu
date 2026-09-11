"""检索配置版本化：把影响召回/融合/精排的参数收敛成可保存、可对比的快照。

一次评测运行会绑定一个 ``RetrievalConfig`` 快照，从而可以在同一评测集上对比
旧版本与新版本，而不是只凭人工感觉判断效果。
"""

from dataclasses import asdict, dataclass, fields
from typing import Any

from app.config import Settings

# 字段 -> 中文名，用于前端展示配置版本差异。
def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "t", "是")
    return bool(value)


_CASTS: dict[str, Any] = {
    "keyword_limit": int, "vector_limit": int, "rrf_k": int,
    "keyword_weight": float, "vector_weight": float,
    "rerank_enabled": _to_bool, "rerank_model": str, "rerank_candidate_limit": int,
    "similarity_threshold": float, "min_evidence_score": float,
    "per_document_limit": int, "final_limit": int, "query_rewrite_synonyms": str,
    "query_rewrite_enabled": _to_bool, "query_rewrite_model": str,
    "context_completion_enabled": _to_bool, "context_history_turns": int,
    "multi_query_enabled": _to_bool, "multi_query_count": int,
    "dictionary_enabled": _to_bool, "spelling_correction_enabled": _to_bool,
}

CONFIG_FIELD_LABELS: dict[str, str] = {
    "keyword_limit": "关键词召回数量",
    "vector_limit": "向量召回数量",
    "rrf_k": "RRF 常数 k",
    "keyword_weight": "关键词 RRF 权重",
    "vector_weight": "向量 RRF 权重",
    "rerank_enabled": "Reranker 开关",
    "rerank_model": "Reranker 模型",
    "rerank_candidate_limit": "精排候选数量",
    "similarity_threshold": "向量相似度阈值",
    "min_evidence_score": "最低证据分数",
    "per_document_limit": "单文档片段上限",
    "final_limit": "最终片段数量",
    "query_rewrite_synonyms": "Query Rewrite 同义词",
    "query_rewrite_enabled": "Query Rewrite 开关",
    "query_rewrite_model": "Query Rewrite 模型",
    "context_completion_enabled": "多轮上下文补全开关",
    "context_history_turns": "上下文轮数",
    "multi_query_enabled": "Multi-query 开关",
    "multi_query_count": "Multi-query 数量",
    "dictionary_enabled": "中文词典开关",
    "spelling_correction_enabled": "拼写纠正开关",
}


@dataclass(frozen=True)
class RetrievalConfig:
    """影响检索质量的可版本化参数集合。"""

    keyword_limit: int = 30
    vector_limit: int = 30
    rrf_k: int = 60
    keyword_weight: float = 1.0
    vector_weight: float = 1.0
    rerank_enabled: bool = False
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_candidate_limit: int = 20
    similarity_threshold: float = 0.55
    min_evidence_score: float = 0.35
    per_document_limit: int = 3
    final_limit: int = 6
    query_rewrite_synonyms: str = ""
    # P2-1：问题改写、上下文补全、多查询与中文检索优化。
    query_rewrite_enabled: bool = False
    query_rewrite_model: str = ""
    context_completion_enabled: bool = False
    context_history_turns: int = 3
    multi_query_enabled: bool = False
    multi_query_count: int = 3
    dictionary_enabled: bool = True
    spelling_correction_enabled: bool = True

    @classmethod
    def from_settings(cls, settings: Settings) -> "RetrievalConfig":
        return cls(
            keyword_limit=settings.search_candidate_limit,
            vector_limit=settings.search_candidate_limit,
            rrf_k=settings.search_rrf_k,
            keyword_weight=1.0,
            vector_weight=1.0,
            rerank_enabled=settings.rerank_enabled,
            rerank_model=settings.rerank_model,
            rerank_candidate_limit=settings.rerank_candidate_limit,
            similarity_threshold=settings.search_vector_min_similarity,
            min_evidence_score=settings.search_min_evidence_score,
            per_document_limit=settings.search_per_document_limit,
            final_limit=settings.rag_source_limit,
            query_rewrite_synonyms=settings.search_synonyms,
            query_rewrite_enabled=settings.query_rewrite_enabled,
            query_rewrite_model=settings.query_rewrite_model,
            context_completion_enabled=settings.context_completion_enabled,
            context_history_turns=settings.context_history_turns,
            multi_query_enabled=settings.multi_query_enabled,
            multi_query_count=settings.multi_query_count,
            dictionary_enabled=settings.dictionary_enabled,
            spelling_correction_enabled=settings.spelling_correction_enabled,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, base: "RetrievalConfig | None" = None) -> "RetrievalConfig":
        """从快照构造配置；缺失或非法字段回退到 base（默认硬编码默认值）。"""
        base = base or cls()
        values = asdict(base)
        for name, caster in _CASTS.items():
            if data is None or name not in data:
                continue
            try:
                values[name] = caster(data[name])
            except (TypeError, ValueError):
                continue
        return cls(**values)


def load_active_config(session, settings: Settings) -> RetrievalConfig:
    """加载默认检索配置版本并叠加到运行时设置；没有默认版本时用 settings。"""
    from sqlalchemy import select

    from app.models import RetrievalConfigVersion

    base = RetrievalConfig.from_settings(settings)
    version = session.scalar(
        select(RetrievalConfigVersion).where(RetrievalConfigVersion.is_default.is_(True)).limit(1)
    )
    if version is None:
        return base
    return RetrievalConfig.from_dict(version.config, base=base)


def _numeric_delta(left_value: Any, right_value: Any) -> float | None:
    """仅对同类型数值字段给出差值；布尔/文本字段返回 None。"""
    if isinstance(left_value, bool) or isinstance(right_value, bool):
        return None
    if isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)):
        return round(float(right_value) - float(left_value), 4)
    return None


def config_diff(left: RetrievalConfig, right: RetrievalConfig) -> list[dict[str, Any]]:
    """返回两个配置版本的字段差异，供前端展示旧值/新值/差值/升降。"""
    differences: list[dict[str, Any]] = []
    for field in fields(RetrievalConfig):
        left_value = getattr(left, field.name)
        right_value = getattr(right, field.name)
        if left_value == right_value:
            continue
        delta = _numeric_delta(left_value, right_value)
        if delta is None:
            direction = "changed"
        elif delta == 0:
            direction = "same"
        else:
            direction = "up" if delta > 0 else "down"
        differences.append({
            "field": field.name,
            "label": CONFIG_FIELD_LABELS.get(field.name, field.name),
            "left": left_value,
            "right": right_value,
            "delta": delta,
            "direction": direction,
        })
    return differences
