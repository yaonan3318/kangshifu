"""知识缺口中心：自动沉淀问题并支持管理员指派、补充资料、重跑与前后对比。"""

from __future__ import annotations

from datetime import UTC, datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.models import KnowledgeGap, KnowledgeGapReason, KnowledgeGapStatus
from app.schemas.answer import AnswerRequest
from app.services.rag import RagService


def normalize_question(text: str) -> str:
    return " ".join((text or "").split()).lower()[:255]


def record_gap(
    session: Session, question: str, reason: KnowledgeGapReason | str, *,
    message_id: uuid.UUID | None = None, answer: str | None = None,
) -> KnowledgeGap | None:
    """按“问题 + 原因”去重累加缺口；任何异常都不影响核心业务。"""
    cleaned = " ".join((question or "").split())
    normalized = normalize_question(cleaned)
    if not normalized:
        return None
    reason_value = reason if isinstance(reason, KnowledgeGapReason) else KnowledgeGapReason(reason)
    try:
        gap = session.scalar(select(KnowledgeGap).where(
            KnowledgeGap.normalized_question == normalized, KnowledgeGap.reason == reason_value,
        ))
        now = datetime.now(UTC)
        if gap is None:
            gap = KnowledgeGap(
                question=cleaned[:2000], normalized_question=normalized, reason=reason_value,
                count=1, sample_message_id=message_id, sample_answer=(answer or None),
                last_seen_at=now,
            )
            session.add(gap)
        else:
            gap.count = (gap.count or 0) + 1
            gap.last_seen_at = now
            if gap.sample_message_id is None:
                gap.sample_message_id = message_id
            if gap.sample_answer is None and answer:
                gap.sample_answer = answer
        session.commit()
        session.refresh(gap)
        return gap
    except Exception:
        # 缺口记录是“尽力而为”，任何失败都不影响核心问答。
        session.rollback()
        return None


class KnowledgeGapService:
    def __init__(self, session: Session, settings: Settings, user=None):
        self.session = session
        self.settings = settings
        self.user = user
        self.rag_factory = RagService

    def list(
        self, *, status: str | None = None, reason: str | None = None,
        assignee_user_id: uuid.UUID | None = None, page: int = 1, page_size: int = 50,
    ) -> tuple[list[KnowledgeGap], int]:
        filters = []
        if status:
            filters.append(KnowledgeGap.status == self._status(status))
        if reason:
            filters.append(KnowledgeGap.reason == self._reason(reason))
        if assignee_user_id is not None:
            filters.append(KnowledgeGap.assignee_user_id == assignee_user_id)
        total = self.session.scalar(select(func.count()).select_from(KnowledgeGap).where(*filters)) or 0
        rows = list(self.session.scalars(
            select(KnowledgeGap).where(*filters)
            .order_by(KnowledgeGap.last_seen_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ))
        return rows, total

    def get(self, gap_id: uuid.UUID) -> KnowledgeGap:
        value = self.session.get(KnowledgeGap, gap_id)
        if value is None:
            raise AppError("KNOWLEDGE_GAP_NOT_FOUND", "知识缺口不存在", 404)
        return value

    def update(
        self, gap_id: uuid.UUID, *, status: str | None = None,
        assignee_user_id: uuid.UUID | None = None, assignee_set: bool = False,
        linked_document_ids: list[uuid.UUID] | None = None, note: str | None = None,
        note_set: bool = False,
    ) -> KnowledgeGap:
        value = self.get(gap_id)
        if status is not None:
            value.status = self._status(status)
        if assignee_set:
            value.assignee_user_id = assignee_user_id
            if assignee_user_id is not None and value.status == KnowledgeGapStatus.OPEN:
                value.status = KnowledgeGapStatus.ASSIGNED
        if linked_document_ids is not None:
            value.linked_document_ids = [str(item) for item in linked_document_ids]
        if note_set:
            value.note = note
        self.session.commit()
        self.session.refresh(value)
        return value

    def statistics(self) -> dict:
        rows = self.session.execute(
            select(KnowledgeGap.status, func.count(KnowledgeGap.id)).group_by(KnowledgeGap.status)
        ).all()
        by_status = {status.value: count for status, count in rows}
        by_reason_rows = self.session.execute(
            select(KnowledgeGap.reason, func.count(KnowledgeGap.id)).group_by(KnowledgeGap.reason)
        ).all()
        by_reason = {reason.value: count for reason, count in by_reason_rows}
        total = sum(by_status.values())
        return {
            "total": total, "open": by_status.get("OPEN", 0),
            "assigned": by_status.get("ASSIGNED", 0), "resolved": by_status.get("RESOLVED", 0),
            "ignored": by_status.get("IGNORED", 0), "by_status": by_status, "by_reason": by_reason,
        }

    async def rerun(self, gap_id: uuid.UUID) -> dict:
        """用当前资料与配置重新回答该问题，保存并返回修复前后对比。"""
        gap = self.get(gap_id)
        before = gap.sample_answer or gap.latest_answer
        service = self.rag_factory(self.session, self.settings, user=self.user)
        text_parts: list[str] = []
        sources: list = []
        confidence = None
        async for event in service.stream(AnswerRequest(question=gap.question)):
            if event.type == "replace":
                text_parts.clear()
            elif event.type == "delta" and event.text:
                text_parts.append(event.text)
            elif event.type == "sources" and event.sources is not None:
                sources = event.sources
            elif event.type == "confidence" and event.confidence is not None:
                confidence = event.confidence
        answer = "".join(text_parts)
        gap.latest_answer = answer
        gap.latest_confidence = confidence.get("tier") if confidence else None
        gap.rerun_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(gap)
        return {
            "gap_id": str(gap.id), "question": gap.question,
            "before": before, "after": answer,
            "confidence": confidence, "source_count": len(sources),
        }

    @staticmethod
    def _status(value: str) -> KnowledgeGapStatus:
        try:
            return KnowledgeGapStatus(value)
        except ValueError as exc:
            raise AppError("KNOWLEDGE_GAP_STATUS_INVALID", "状态不正确", 422) from exc

    @staticmethod
    def _reason(value: str) -> KnowledgeGapReason:
        try:
            return KnowledgeGapReason(value)
        except ValueError as exc:
            raise AppError("KNOWLEDGE_GAP_REASON_INVALID", "原因不正确", 422) from exc
