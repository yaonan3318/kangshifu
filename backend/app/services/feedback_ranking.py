"""反馈影响检索排序。

原则（P2-7B）：
- 反馈只在**已经通过关键词/向量召回**的候选上做乘法微调，绝不让未召回、
  无权限、停用或已删除的资料进入结果；
- 聚合粒度为 ``knowledge_base_id + chunk_id + query_fingerprint``，
  不做文档级全局累计，避免“某片段受欢迎影响所有查询”；
- 只有不同用户数达到门槛才生效，单用户重复提交只算一次；
- 正负调整有界：正向最多 ``max_positive_boost``，负向最多 ``max_negative_penalty``。

本模块同时保留 P2 早期按文档聚合的兼容接口（``boosts``/``recompute``），
供既有统计与测试使用；生产检索链路使用新的片段级 ``adjustments``。
"""

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    AnswerFeedback, AnswerFeedbackDocument, DocumentFeedbackStats, FeedbackAggregate,
    FeedbackCase, FeedbackCaseStatus, FeedbackRating, FeedbackRetrievalSnapshot,
    FeedbackType, User,
)

_FINGERPRINT_PATTERN = re.compile(r"[^\w\u4e00-\u9fff]+")


def query_fingerprint(question: str | None) -> str:
    """简单可解释的问题指纹：小写、去空白与标点后取 SHA-256。"""
    normalized = re.sub(r"\s+", "", (question or "").strip().lower())
    normalized = _FINGERPRINT_PATTERN.sub("", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class FeedbackAdjustment:
    """单条候选片段的反馈微调结果，供检索实验室解释排序变化。"""

    chunk_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    query_fingerprint: str
    positive_users: int
    negative_users: int
    effective_users: int
    admin_verified_positive: int
    admin_verified_negative: int
    raw_feedback: float
    bounded_feedback: float
    boost: float
    applied: bool
    reason: str

    def to_dict(self) -> dict:
        return {
            "chunk_id": str(self.chunk_id),
            "knowledge_base_id": str(self.knowledge_base_id),
            "query_fingerprint": self.query_fingerprint,
            "positive_users": self.positive_users,
            "negative_users": self.negative_users,
            "distinct_user_count": self.effective_users,
            "admin_verified_positive": self.admin_verified_positive,
            "admin_verified_negative": self.admin_verified_negative,
            "raw_feedback": round(self.raw_feedback, 6),
            "bounded_feedback": round(self.bounded_feedback, 6),
            "feedback_boost": round(self.boost, 6),
            "feedback_applied": self.applied,
            "feedback_reason": self.reason,
        }


def compute_feedback_adjustment(
    *,
    positive_users: int,
    negative_users: int,
    admin_verified_positive: int = 0,
    admin_verified_negative: int = 0,
    min_distinct_users: int = 5,
    max_positive_boost: float = 0.08,
    max_negative_penalty: float = 0.10,
    admin_verified_weight: float = 1.5,
) -> tuple[float, float, float, bool, str]:
    """有界平滑公式，返回 (raw, bounded, boost, applied, reason)。

    - 未达到不同用户门槛时不生效；
    - 管理员确认的有效反馈按 ``admin_verified_weight`` 获得额外权重，但总上限不变；
    - 使用乘法微调，避免不同检索分数尺度混乱。
    """
    positive_users = max(0, int(positive_users))
    negative_users = max(0, int(negative_users))
    effective = positive_users + negative_users
    if effective <= 0:
        return 0.0, 0.0, 0.0, False, "no_samples"
    if effective < max(1, int(min_distinct_users)):
        return 0.0, 0.0, 0.0, False, "insufficient_distinct_users"

    positive_rate = positive_users / effective
    negative_rate = negative_users / effective
    verified = (
        (int(admin_verified_positive) - int(admin_verified_negative)) / effective
        * max(0.0, float(admin_verified_weight) - 1.0)
    )
    raw = _clamp(positive_rate - negative_rate + verified, -1.0, 1.0)
    bounded = raw
    if raw > 0:
        boost = raw * _clamp(float(max_positive_boost), 0.0, 1.0)
    else:
        boost = raw * _clamp(float(max_negative_penalty), 0.0, 1.0)
    return raw, bounded, boost, True, "applied"


class FeedbackRankingService:
    def __init__(self, session: Session, settings: Settings, config=None):
        self.session = session
        self.settings = settings
        # 可版本化检索配置；未传入时使用运行时设置。
        self.config = config

    # ------------------------------------------------------------ 配置

    def _value(self, config_name: str, setting_name: str, default):
        if self.config is not None:
            value = getattr(self.config, config_name, None)
            if value is not None:
                return value
        return getattr(self.settings, setting_name, default)

    @property
    def enabled(self) -> bool:
        return bool(self._value(
            "feedback_ranking_enabled", "search_feedback_ranking_enabled", False,
        ))

    def _parameters(self) -> dict:
        return {
            "min_distinct_users": max(1, int(self._value(
                "feedback_min_distinct_users", "search_feedback_min_distinct_users", 5))),
            "max_positive_boost": _clamp(float(self._value(
                "feedback_max_positive_boost", "search_feedback_max_positive_boost", 0.08)), 0.0, 0.10),
            "max_negative_penalty": _clamp(float(self._value(
                "feedback_max_negative_penalty", "search_feedback_max_negative_penalty", 0.10)), 0.0, 0.15),
            "admin_verified_weight": _clamp(float(self._value(
                "feedback_admin_verified_weight", "search_feedback_admin_verified_weight", 1.5)), 0.0, 2.0),
            "valid_days": max(0, int(self._value(
                "feedback_valid_days", "search_feedback_valid_days", 0))),
            "exclude_disabled_users": bool(self._value(
                "feedback_exclude_disabled_users", "search_feedback_exclude_disabled_users", True)),
            "only_processed": bool(self._value(
                "feedback_only_processed", "search_feedback_only_processed", False)),
        }

    # ------------------------------------------------------------ 片段级聚合

    def adjustments(
        self, query: str, items: list[tuple[uuid.UUID, uuid.UUID]],
    ) -> dict[uuid.UUID, FeedbackAdjustment]:
        """返回 ``chunk_id -> FeedbackAdjustment``；只覆盖传入的候选。"""
        if not self.enabled or not items:
            return {}
        parameters = self._parameters()
        fingerprint = query_fingerprint(query)
        wanted_chunks = {chunk_id for chunk_id, _ in items}
        wanted_keys = {(chunk_id, kb_id) for chunk_id, kb_id in items}
        groups = self._collect_samples(
            fingerprint=fingerprint, wanted_chunks=wanted_chunks, parameters=parameters,
        )
        result: dict[uuid.UUID, FeedbackAdjustment] = {}
        for (chunk_id, kb_id), bucket in groups.items():
            if (chunk_id, kb_id) not in wanted_keys:
                continue
            raw, bounded, boost, applied, reason = compute_feedback_adjustment(
                positive_users=len(bucket["positive"]),
                negative_users=len(bucket["negative"]),
                admin_verified_positive=len(bucket["verified_positive"]),
                admin_verified_negative=len(bucket["verified_negative"]),
                min_distinct_users=parameters["min_distinct_users"],
                max_positive_boost=parameters["max_positive_boost"],
                max_negative_penalty=parameters["max_negative_penalty"],
                admin_verified_weight=parameters["admin_verified_weight"],
            )
            result[chunk_id] = FeedbackAdjustment(
                chunk_id=chunk_id, knowledge_base_id=kb_id, query_fingerprint=fingerprint,
                positive_users=len(bucket["positive"]), negative_users=len(bucket["negative"]),
                effective_users=len(bucket["positive"]) + len(bucket["negative"]),
                admin_verified_positive=len(bucket["verified_positive"]),
                admin_verified_negative=len(bucket["verified_negative"]),
                raw_feedback=raw, bounded_feedback=bounded, boost=boost,
                applied=applied, reason=reason,
            )
        return result

    def _collect_samples(
        self, *, fingerprint: str, wanted_chunks: set[uuid.UUID] | None, parameters: dict,
    ) -> dict[tuple[uuid.UUID, uuid.UUID], dict]:
        """从反馈快照实时聚合；保证不同用户、停用用户、忽略反馈等规则生效。"""
        rows = self.session.execute(
            select(AnswerFeedback, FeedbackRetrievalSnapshot, FeedbackCase)
            .join(FeedbackRetrievalSnapshot, FeedbackRetrievalSnapshot.feedback_id == AnswerFeedback.id)
            .outerjoin(FeedbackCase, FeedbackCase.feedback_id == AnswerFeedback.id)
            .where(AnswerFeedback.query_fingerprint == fingerprint)
        ).all()
        if not rows:
            return {}
        user_ids = {feedback.user_id for feedback, _, _ in rows if feedback.user_id is not None}
        enabled_users: dict[uuid.UUID, bool] = {}
        if user_ids:
            enabled_users = dict(self.session.execute(
                select(User.id, User.enabled).where(User.id.in_(user_ids))
            ).all())
        now = datetime.now(UTC)
        groups: dict[tuple[uuid.UUID, uuid.UUID], dict] = {}
        for feedback, snapshot, case in rows:
            if not self._countable(feedback, case, parameters, enabled_users, now):
                continue
            polarity = "positive" if feedback.rating == FeedbackRating.UP else "negative"
            verified = bool(case and case.status == FeedbackCaseStatus.RESOLVED)
            for chunk in snapshot.chunks or []:
                chunk_id = _as_uuid(chunk.get("chunk_id"))
                kb_id = _as_uuid(chunk.get("knowledge_base_id"))
                if chunk_id is None or kb_id is None:
                    continue
                if wanted_chunks is not None and chunk_id not in wanted_chunks:
                    continue
                bucket = groups.setdefault((chunk_id, kb_id), {
                    "positive": set(), "negative": set(),
                    "verified_positive": set(), "verified_negative": set(),
                })
                bucket[polarity].add(feedback.user_id)
                if verified:
                    bucket[f"verified_{polarity}"].add(feedback.user_id)
        return groups

    @staticmethod
    def _countable(feedback, case, parameters: dict, enabled_users: dict, now: datetime) -> bool:
        if feedback.user_id is None:
            return False
        if parameters["exclude_disabled_users"] and not enabled_users.get(feedback.user_id, False):
            return False
        if case is not None and case.status == FeedbackCaseStatus.IGNORED:
            return False
        if parameters["only_processed"] and (case is None or case.status == FeedbackCaseStatus.PENDING):
            return False
        if parameters["valid_days"] > 0:
            created = feedback.created_at
            if created is not None:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                if created < now - timedelta(days=parameters["valid_days"]):
                    return False
        return True

    def recompute_aggregates(self) -> None:
        """把实时聚合结果落库到 ``feedback_aggregates``，供统计页展示。"""
        parameters = self._parameters()
        fingerprints = list(self.session.scalars(
            select(AnswerFeedback.query_fingerprint)
            .where(AnswerFeedback.query_fingerprint.is_not(None))
            .distinct()
        ))
        wanted: set[tuple[uuid.UUID, uuid.UUID, str]] = set()
        for fingerprint in fingerprints:
            groups = self._collect_samples(
                fingerprint=fingerprint, wanted_chunks=None, parameters=parameters,
            )
            for (chunk_id, kb_id), bucket in groups.items():
                key = (kb_id, chunk_id, fingerprint)
                wanted.add(key)
                raw, bounded, boost, _, _ = compute_feedback_adjustment(
                    positive_users=len(bucket["positive"]),
                    negative_users=len(bucket["negative"]),
                    admin_verified_positive=len(bucket["verified_positive"]),
                    admin_verified_negative=len(bucket["verified_negative"]),
                    **{name: parameters[name] for name in (
                        "min_distinct_users", "max_positive_boost",
                        "max_negative_penalty", "admin_verified_weight",
                    )},
                )
                row = self.session.scalar(select(FeedbackAggregate).where(
                    FeedbackAggregate.knowledge_base_id == kb_id,
                    FeedbackAggregate.chunk_id == chunk_id,
                    FeedbackAggregate.query_fingerprint == fingerprint,
                ))
                if row is None:
                    row = FeedbackAggregate(
                        knowledge_base_id=kb_id, chunk_id=chunk_id, query_fingerprint=fingerprint,
                    )
                    self.session.add(row)
                row.positive_users = len(bucket["positive"])
                row.negative_users = len(bucket["negative"])
                row.effective_users = len(bucket["positive"]) + len(bucket["negative"])
                row.admin_verified_positive = len(bucket["verified_positive"])
                row.admin_verified_negative = len(bucket["verified_negative"])
                row.raw_feedback = raw
                row.bounded_feedback = bounded
                row.feedback_boost = boost
        for row in self.session.scalars(select(FeedbackAggregate)):
            if (row.knowledge_base_id, row.chunk_id, row.query_fingerprint) not in wanted:
                self.session.delete(row)
        self.session.commit()

    # ------------------------------------------------------------ 兼容旧接口

    def boosts(self, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, float]:
        """返回每个文档的反馈调整分；样本不足或关闭时为 0（P2 早期兼容接口）。"""
        if not self.enabled or not document_ids:
            return {}
        unique_ids = list(dict.fromkeys(document_ids))
        rows = self.session.execute(
            select(
                DocumentFeedbackStats.document_id,
                DocumentFeedbackStats.sample_count,
                DocumentFeedbackStats.up_count,
                DocumentFeedbackStats.down_count,
            ).where(DocumentFeedbackStats.document_id.in_(unique_ids))
        ).all()
        minimum = max(1, self.settings.search_feedback_min_samples)
        cap = abs(self.settings.search_feedback_max_boost)
        boosts: dict[uuid.UUID, float] = {}
        for document_id, sample_count, up_count, down_count in rows:
            if (sample_count or 0) < minimum:
                continue
            net = (up_count - down_count) / sample_count
            boosts[document_id] = max(-cap, min(cap, net * cap))
        return boosts

    def recompute(self, document_id: uuid.UUID | None = None) -> None:
        """根据反馈关联表重新聚合文档统计；供反馈写入后调用（兼容接口）。"""
        up = func.count(case((AnswerFeedback.rating == FeedbackRating.UP, 1)))
        down = func.count(case((AnswerFeedback.rating != FeedbackRating.UP, 1)))
        statement = (
            select(AnswerFeedbackDocument.document_id, func.count(AnswerFeedbackDocument.id), up, down)
            .join(AnswerFeedback, AnswerFeedback.id == AnswerFeedbackDocument.feedback_id)
            .group_by(AnswerFeedbackDocument.document_id)
        )
        if document_id is not None:
            statement = statement.where(AnswerFeedbackDocument.document_id == document_id)
        rows = self.session.execute(statement).all()
        seen: set[uuid.UUID] = set()
        for doc_id, sample_count, up_count, down_count in rows:
            seen.add(doc_id)
            stats = self.session.get(DocumentFeedbackStats, doc_id)
            if stats is None:
                stats = DocumentFeedbackStats(document_id=doc_id)
                self.session.add(stats)
            stats.sample_count = int(sample_count or 0)
            stats.up_count = int(up_count or 0)
            stats.down_count = int(down_count or 0)
            stats.score = 0.0 if not stats.sample_count else (stats.up_count - stats.down_count) / stats.sample_count
        if document_id is not None and document_id not in seen:
            stats = self.session.get(DocumentFeedbackStats, document_id)
            if stats is not None:
                self.session.delete(stats)
        self.session.commit()

    def statistics(self, limit: int = 100) -> list[dict]:
        rows = self.session.scalars(
            select(DocumentFeedbackStats)
            .order_by(DocumentFeedbackStats.sample_count.desc())
            .limit(limit)
        ).all()
        return [{
            "document_id": item.document_id,
            "up_count": item.up_count,
            "down_count": item.down_count,
            "sample_count": item.sample_count,
            "score": item.score,
            "boost": 0.0 if item.sample_count < max(1, self.settings.search_feedback_min_samples)
            else max(-abs(self.settings.search_feedback_max_boost), min(abs(self.settings.search_feedback_max_boost), item.score * abs(self.settings.search_feedback_max_boost))),
        } for item in rows]

    def aggregate_statistics(self, limit: int = 200) -> list[dict]:
        """片段级聚合样本，供反馈数据分析展示。"""
        rows = self.session.scalars(
            select(FeedbackAggregate)
            .order_by(FeedbackAggregate.effective_users.desc())
            .limit(limit)
        ).all()
        return [{
            "knowledge_base_id": item.knowledge_base_id,
            "chunk_id": item.chunk_id,
            "query_fingerprint": item.query_fingerprint,
            "positive_users": item.positive_users,
            "negative_users": item.negative_users,
            "distinct_user_count": item.effective_users,
            "raw_feedback": item.raw_feedback,
            "bounded_feedback": item.bounded_feedback,
            "feedback_boost": item.feedback_boost,
            "updated_at": item.updated_at,
        } for item in rows]


def _as_uuid(value) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None
