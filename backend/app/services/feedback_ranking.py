"""反馈影响检索排序（第一版默认关闭）。

原则：
- 先记录反馈，样本达到门槛后才产生小幅影响；
- 正/负反馈只做不超过 ``search_feedback_max_boost`` 的加减分；
- 只作用于已经通过关键词/语义召回且满足最低证据阈值的候选，
  不会让无关联、无权限或已删除的资料重新出现。
"""

import uuid

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AnswerFeedback, DocumentFeedbackStats, FeedbackRating


class FeedbackRankingService:
    def __init__(self, session: Session, settings: Settings):
        self.session = session
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.search_feedback_ranking_enabled)

    def boosts(self, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, float]:
        """返回每个文档的反馈调整分；样本不足或关闭时为 0。"""
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
        """根据反馈重新聚合文档统计；供反馈写入后调用。"""
        up = func.count(case((AnswerFeedback.rating == FeedbackRating.UP, 1)))
        down = func.count(case((AnswerFeedback.rating == FeedbackRating.DOWN, 1)))
        statement = (
            select(AnswerFeedback.document_id, func.count(AnswerFeedback.id), up, down)
            .where(AnswerFeedback.document_id.is_not(None))
            .group_by(AnswerFeedback.document_id)
        )
        if document_id is not None:
            statement = statement.where(AnswerFeedback.document_id == document_id)
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
