"""历史负反馈复验服务（P2-7C）。

复验使用历史原问题、当前文档版本与当前发布中的检索配置重新执行检索和回答，
保存新回答/引用/分数/耗时用于新旧并排对比，**不覆盖**原始回答快照。
"""

import uuid
from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.models import (
    AnswerFeedback, ChatMessage, ChatMessageSource, FeedbackCase, FeedbackCaseStatus,
    FeedbackVerificationRun, RetrievalConfigVersion, User, VerificationStatus,
)
from app.schemas.answer import AnswerRequest
from app.services.rag import RagService
from app.services.retrieval_config import load_active_config


class FeedbackVerificationService:
    def __init__(self, session: Session, settings: Settings):
        self.session = session
        self.settings = settings
        self.rag_factory = RagService

    async def verify(
        self, case_id: uuid.UUID, actor: User, *, conclusion: str | None = None,
    ) -> FeedbackVerificationRun:
        case = self.session.get(FeedbackCase, case_id)
        if case is None:
            raise AppError("FEEDBACK_CASE_NOT_FOUND", "反馈工单不存在", 404)
        feedback = self.session.get(AnswerFeedback, case.feedback_id)
        if feedback is None:
            raise AppError("FEEDBACK_NOT_FOUND", "反馈不存在", 404)
        question = (feedback.question_snapshot or "").strip()
        if not question:
            raise AppError("VERIFY_QUESTION_MISSING", "该反馈缺少原始问题，无法复验", 409)

        before_sources = self._before_sources(feedback)
        config = load_active_config(self.session, self.settings)
        config_version_id = self.session.scalar(
            select(RetrievalConfigVersion.id).where(RetrievalConfigVersion.is_default.is_(True)).limit(1)
        )
        run = FeedbackVerificationRun(
            case_id=case.id, feedback_id=feedback.id, status=VerificationStatus.RUNNING,
            question=question, before_answer=feedback.answer_snapshot,
            before_sources=before_sources, before_config_version_id=feedback.retrieval_config_version_id,
            after_config_version_id=config_version_id, created_by=actor.id,
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)

        verification_user = self._verification_identity(feedback, actor)
        started = perf_counter()
        try:
            answer, sources, metrics, scope = await self._run_question(question, verification_user, config)
            run.after_answer = answer
            run.after_sources = sources
            run.base_score = self._first_score(sources, "base_score")
            run.final_score = self._first_score(sources, "final_score")
            run.no_answer = not sources or scope == "NONE"
            run.duration_ms = int((perf_counter() - started) * 1000)
            run.status = VerificationStatus.FAILED if run.no_answer else VerificationStatus.PASSED
            run.admin_conclusion = conclusion
        except Exception as exc:  # pragma: no cover - 依赖外部模型，失败必须可解释
            run.status = VerificationStatus.ERROR
            run.error_message = str(exc)[:2000]
            run.duration_ms = int((perf_counter() - started) * 1000)
        run.completed_at = datetime.now(UTC)
        case.last_verification_result = run.status
        if config_version_id is not None:
            case.fix_config_version_id = case.fix_config_version_id or config_version_id
        self.session.commit()
        self.session.refresh(run)
        return run

    async def _run_question(self, question: str, user, config) -> tuple[str, list[dict], dict, str | None]:
        service = self.rag_factory(
            self.session, self.settings, user=user, config=config, source_limit=config.final_limit,
        )
        text_parts: list[str] = []
        sources: list = []
        metrics: dict = {}
        scope = None
        async for event in service.stream(AnswerRequest(question=question)):
            if event.type == "replace":
                text_parts.clear()
            elif event.type == "delta" and event.text:
                text_parts.append(event.text)
            elif event.type == "sources" and event.sources is not None:
                sources = event.sources
            elif event.type == "metrics" and event.metrics is not None:
                metrics = event.metrics
            elif event.type == "done" and event.scope is not None:
                scope = event.scope.value
        payload = [{
            "citation_number": getattr(item, "citation_number", None),
            "document_id": str(getattr(item, "document_id", "")),
            "document_name": getattr(item, "document_name", None),
            "chunk_id": str(getattr(item, "chunk_id", "")),
            "content": getattr(item, "content", None),
            "base_score": getattr(item, "base_score", None),
            "final_score": getattr(item, "final_score", None),
            "feedback_applied": getattr(item, "feedback_applied", False),
        } for item in sources]
        return "".join(text_parts), payload, metrics, scope

    def _before_sources(self, feedback: AnswerFeedback) -> list[dict]:
        rows = self.session.scalars(
            select(ChatMessageSource).where(ChatMessageSource.message_id == feedback.message_id)
            .order_by(ChatMessageSource.citation_number)
        ).all()
        return [{
            "citation_number": item.citation_number,
            "document_id": str(item.document_id),
            "document_name": item.document_name,
            "chunk_id": str(item.chunk_id),
            "content": item.content_snapshot,
            "score": item.score,
        } for item in rows]

    def _verification_identity(self, feedback: AnswerFeedback, actor: User):
        """优先用原提问人（仍启用）复现其权限范围，否则退回管理员身份。"""
        if feedback.user_id is not None:
            original = self.session.get(User, feedback.user_id)
            if original is not None and original.enabled:
                return original
        return actor

    @staticmethod
    def _first_score(sources: list[dict], key: str) -> float | None:
        for item in sources:
            value = item.get(key)
            if value is not None:
                return float(value)
        return None
