"""反馈治理服务：同一用户去重、上下文快照、处理队列、历史记录与统计。

设计约束（P2-7A/C）：
- ``user_id + message_id`` 是一条当前有效反馈；重复提交覆盖原记录；
- 反馈发生时冻结回答/引用/检索配置等上下文，回答或文档后来变化也不丢历史；
- 负反馈进入处理队列，状态流转由后端枚举与迁移表校验；
- 每次变更追加 ``feedback_history``，管理操作另写审计日志。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.models import (
    AnswerFeedback, AnswerFeedbackDocument, Assistant, ChatMessage, ChatMessageRole,
    ChatMessageSource, ChatSession, Document, FeedbackCase,
    FeedbackCaseEvent, FeedbackCaseStatus, FeedbackHistory, FeedbackPriority,
    FeedbackRating, FeedbackRetrievalSnapshot, FeedbackType, FeedbackVerificationRun,
    KnowledgeBase, RetrievalConfigVersion, User,
)
from app.services.feedback_ranking import FeedbackRankingService, query_fingerprint
from app.services.knowledge_gaps import record_gap

CASE_STATUS_VALUES = [item.value for item in FeedbackCaseStatus]
CASE_PRIORITY_VALUES = [item.value for item in FeedbackPriority]

# 允许的工单状态流转；后端强制校验，不能接受任意字符串。
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    FeedbackCaseStatus.PENDING.value: {
        FeedbackCaseStatus.PROCESSING.value, FeedbackCaseStatus.WAIT_VERIFY.value,
        FeedbackCaseStatus.RESOLVED.value, FeedbackCaseStatus.IGNORED.value,
    },
    FeedbackCaseStatus.PROCESSING.value: {
        FeedbackCaseStatus.WAIT_VERIFY.value, FeedbackCaseStatus.RESOLVED.value,
        FeedbackCaseStatus.IGNORED.value,
    },
    FeedbackCaseStatus.WAIT_VERIFY.value: {
        FeedbackCaseStatus.PROCESSING.value, FeedbackCaseStatus.RESOLVED.value,
        FeedbackCaseStatus.IGNORED.value,
    },
    FeedbackCaseStatus.RESOLVED.value: {
        FeedbackCaseStatus.PROCESSING.value, FeedbackCaseStatus.WAIT_VERIFY.value,
    },
    FeedbackCaseStatus.IGNORED.value: {FeedbackCaseStatus.PROCESSING.value},
}

NEGATIVE_REASONS = {
    "缺失知识", "引用不正确", "引用错误", "内容不准确", "资料已经过期",
    "资料过期", "没有找到已有资料", "答非所问", "回答不完整",
}


class FeedbackService:
    def __init__(self, session: Session, settings: Settings):
        self.session = session
        self.settings = settings

    # ------------------------------------------------------------ 提交反馈

    def submit(
        self, user: User, *, message_id: uuid.UUID, rating: str, feedback_type: str | None = None,
        reasons: list[str] | None = None, comment: str | None = None,
    ) -> AnswerFeedback:
        message = self._find_message(message_id)
        self._require_own(message, user)
        sources = self._sources(message_id)
        context = self._build_context(message, sources)
        try:
            rating_value = FeedbackRating(rating)
        except ValueError as exc:
            raise AppError("INVALID_FEEDBACK", "反馈类型不合法", 400) from exc
        type_value = FeedbackType(feedback_type or rating_value.value)

        existing = self.session.scalar(select(AnswerFeedback).where(
            AnswerFeedback.message_id == message_id, AnswerFeedback.user_id == user.id,
        ))
        if existing is not None:
            self._record_history(
                existing, user, "UPDATED",
                new_rating=rating_value.value, new_reasons=list(reasons or []),
                new_comment=comment,
            )
            existing.rating = rating_value
            existing.feedback_type = type_value
            existing.reasons = list(reasons or [])
            existing.comment = comment
            existing.resolved_at = None
            existing.resolution_note = None
            existing.updated_at = datetime.now(UTC)
            feedback = existing
        else:
            feedback = AnswerFeedback(
                message_id=message_id, user_id=user.id, rating=rating_value,
                feedback_type=type_value, reasons=list(reasons or []), comment=comment,
            )
            self.session.add(feedback)
            self.session.flush()
            self._record_history(
                feedback, user, "CREATED",
                new_rating=rating_value.value, new_reasons=list(reasons or []), new_comment=comment,
            )
        self._apply_context(feedback, context)
        self._replace_document_links(feedback, sources)
        self._replace_retrieval_snapshot(feedback, sources, context["retrieval_config_version_id"])
        self.session.flush()

        is_negative = rating_value != FeedbackRating.UP
        if is_negative:
            self._ensure_case(feedback, user)
        else:
            self._ignore_open_case(feedback, user)
        self.session.commit()
        self.session.refresh(feedback)

        if rating_value != FeedbackRating.UP:
            wrong = any("引用" in str(item) for item in (reasons or []))
            record_gap(
                self.session, context["question_snapshot"] or "",
                "WRONG_DOCUMENT" if wrong else "NEGATIVE_FEEDBACK",
                message_id=message.id, answer=message.content,
            )
        self._recompute_ranking(feedback, sources)
        return feedback

    def _recompute_ranking(self, feedback: AnswerFeedback, sources: list[ChatMessageSource]) -> None:
        ranking = FeedbackRankingService(self.session, self.settings)
        document_ids = {source.document_id for source in sources}
        if feedback.document_id is not None:
            document_ids.add(feedback.document_id)
        for document_id in document_ids:
            ranking.recompute(document_id)
        try:
            ranking.recompute_aggregates()
        except Exception:  # pragma: no cover - 聚合失败不影响反馈写入
            self.session.rollback()

    # ------------------------------------------------------------ 上下文快照

    def _build_context(self, message: ChatMessage, sources: list[ChatMessageSource]) -> dict:
        chat_session = self.session.get(ChatSession, message.session_id)
        assistant_id = chat_session.assistant_id if chat_session else None
        document_ids: list[uuid.UUID] = []
        chunk_ids: list[uuid.UUID] = []
        knowledge_base_ids: list[uuid.UUID] = []
        document_versions: list[dict] = []
        for source in sources:
            if source.document_id not in document_ids:
                document_ids.append(source.document_id)
            if source.chunk_id not in chunk_ids:
                chunk_ids.append(source.chunk_id)
            document = self.session.get(Document, source.document_id)
            if document is not None:
                if document.knowledge_base_id not in knowledge_base_ids:
                    knowledge_base_ids.append(document.knowledge_base_id)
                document_versions.append({
                    "document_id": str(source.document_id),
                    "version_number": source.document_version or document.version_number,
                    "current_version": document.version_number,
                })
        question = self._question_for(message)
        return {
            "chat_session_id": message.session_id,
            "assistant_id": assistant_id,
            "question_snapshot": question,
            "answer_snapshot": message.content,
            "knowledge_scope": message.knowledge_scope,
            "chunk_ids": [str(item) for item in chunk_ids],
            "document_ids": [str(item) for item in document_ids],
            "document_versions": document_versions,
            "knowledge_base_ids": [str(item) for item in knowledge_base_ids],
            "retrieval_config_version_id": self._active_config_version_id(),
            "answer_model": self._answer_model(message),
            "answer_provider": message.provider.value if message.provider else None,
            "query_fingerprint": query_fingerprint(question),
        }

    def _apply_context(self, feedback: AnswerFeedback, context: dict) -> None:
        feedback.chat_session_id = context["chat_session_id"]
        feedback.assistant_id = context["assistant_id"]
        feedback.question_snapshot = context["question_snapshot"]
        feedback.answer_snapshot = context["answer_snapshot"]
        feedback.knowledge_scope = context["knowledge_scope"]
        feedback.chunk_ids = context["chunk_ids"]
        feedback.document_ids = context["document_ids"]
        feedback.document_versions = context["document_versions"]
        feedback.knowledge_base_ids = context["knowledge_base_ids"]
        feedback.retrieval_config_version_id = context["retrieval_config_version_id"]
        feedback.answer_model = context["answer_model"]
        feedback.answer_provider = context["answer_provider"]
        feedback.query_fingerprint = context["query_fingerprint"]
        # 兼容旧的单文档字段：恰好一个引用文档时回填。
        feedback.document_id = (
            uuid.UUID(context["document_ids"][0]) if len(context["document_ids"]) == 1 else None
        )

    def _replace_document_links(self, feedback: AnswerFeedback, sources: list[ChatMessageSource]) -> None:
        self.session.execute(delete(AnswerFeedbackDocument).where(
            AnswerFeedbackDocument.feedback_id == feedback.id
        ))
        seen: set[uuid.UUID] = set()
        for source in sources:
            if source.document_id in seen:
                continue
            seen.add(source.document_id)
            self.session.add(AnswerFeedbackDocument(
                feedback_id=feedback.id, document_id=source.document_id,
                citation_number=source.citation_number,
            ))

    def _replace_retrieval_snapshot(
        self, feedback: AnswerFeedback, sources: list[ChatMessageSource], config_version_id,
    ) -> None:
        self.session.execute(delete(FeedbackRetrievalSnapshot).where(
            FeedbackRetrievalSnapshot.feedback_id == feedback.id
        ))
        chunks: list[dict] = []
        for source in sources:
            document = self.session.get(Document, source.document_id)
            chunks.append({
                "chunk_id": str(source.chunk_id),
                "document_id": str(source.document_id),
                "knowledge_base_id": str(document.knowledge_base_id) if document else None,
                "score": source.score,
                "retrieval_rank": source.retrieval_rank,
                "citation_number": source.citation_number,
            })
        self.session.add(FeedbackRetrievalSnapshot(
            feedback_id=feedback.id, retrieval_config_version_id=config_version_id, chunks=chunks,
        ))

    # ------------------------------------------------------------ 历史

    def _record_history(
        self, feedback: AnswerFeedback, actor: User | None, change_type: str, *,
        new_rating=None, new_reasons=None, new_comment=None,
    ) -> FeedbackHistory:
        history = FeedbackHistory(
            feedback_id=feedback.id, change_type=change_type,
            previous_rating=feedback.rating.value if feedback.rating else None,
            new_rating=new_rating,
            previous_reasons=list(feedback.reasons or []),
            new_reasons=list(new_reasons or []),
            previous_comment=feedback.comment,
            new_comment=new_comment,
            changed_by=actor.id if actor else None,
        )
        self.session.add(history)
        return history

    # ------------------------------------------------------------ 工单

    def _ensure_case(self, feedback: AnswerFeedback, actor: User | None) -> FeedbackCase:
        case = self.session.scalar(select(FeedbackCase).where(FeedbackCase.feedback_id == feedback.id))
        if case is not None:
            return case
        case = FeedbackCase(
            feedback_id=feedback.id, status=FeedbackCaseStatus.PENDING,
            priority=FeedbackPriority.NORMAL,
        )
        self.session.add(case)
        self.session.flush()
        self._add_event(case, "CREATED", actor=actor, to_status=FeedbackCaseStatus.PENDING.value,
                        note="负反馈进入处理队列")
        return case

    def _ignore_open_case(self, feedback: AnswerFeedback, actor: User | None) -> None:
        case = self.session.scalar(select(FeedbackCase).where(FeedbackCase.feedback_id == feedback.id))
        if case is None:
            return
        if case.status in (FeedbackCaseStatus.PENDING, FeedbackCaseStatus.PROCESSING, FeedbackCaseStatus.WAIT_VERIFY):
            previous = case.status.value
            case.status = FeedbackCaseStatus.IGNORED
            self._add_event(case, "RATING_CHANGED_POSITIVE", actor=actor,
                            from_status=previous, to_status=FeedbackCaseStatus.IGNORED.value,
                            note="用户已改为点赞，自动关闭处理工单")

    def _add_event(
        self, case: FeedbackCase, event_type: str, *, actor: User | None,
        from_status: str | None = None, to_status: str | None = None,
        note: str | None = None, detail: dict | None = None,
    ) -> FeedbackCaseEvent:
        event = FeedbackCaseEvent(
            case_id=case.id, event_type=event_type, from_status=from_status,
            to_status=to_status, actor_id=actor.id if actor else None,
            note=note, detail=detail or {},
        )
        self.session.add(event)
        return event

    def get_case(self, case_id: uuid.UUID) -> FeedbackCase:
        case = self.session.get(FeedbackCase, case_id)
        if case is None:
            raise AppError("FEEDBACK_CASE_NOT_FOUND", "反馈工单不存在", 404)
        return case

    def assign_case(
        self, case_id: uuid.UUID, actor: User, *, assignee_id: uuid.UUID | None,
        priority: str | None = None, note: str | None = None,
    ) -> FeedbackCase:
        case = self.get_case(case_id)
        if assignee_id is not None:
            assignee = self.session.get(User, assignee_id)
            if assignee is None or not assignee.enabled:
                raise AppError("ASSIGNEE_NOT_FOUND", "负责人不存在或已停用", 400)
        if priority is not None:
            self._validate_priority(priority)
        previous_status = case.status.value
        case.assignee_id = assignee_id
        if priority is not None:
            case.priority = FeedbackPriority(priority)
        if case.status == FeedbackCaseStatus.PENDING:
            case.status = FeedbackCaseStatus.PROCESSING
            case.first_handled_at = case.first_handled_at or datetime.now(UTC)
        self._add_event(
            case, "ASSIGNED", actor=actor, from_status=previous_status,
            to_status=case.status.value, note=note,
            detail={
                "assignee_id": str(assignee_id) if assignee_id else None,
                "priority": case.priority.value,
            },
        )
        self.session.commit()
        self.session.refresh(case)
        return case

    def update_case(
        self, case_id: uuid.UUID, actor: User, *, status: str | None = None,
        priority: str | None = None, admin_note: str | None = None,
        conclusion: str | None = None, fix_document_id: uuid.UUID | None = None,
        fix_config_version_id: uuid.UUID | None = None, note: str | None = None,
    ) -> FeedbackCase:
        case = self.get_case(case_id)
        previous_status = case.status.value
        if priority is not None:
            self._validate_priority(priority)
            case.priority = FeedbackPriority(priority)
        if admin_note is not None:
            case.admin_note = admin_note
        if conclusion is not None:
            case.conclusion = conclusion
        if fix_document_id is not None:
            if self.session.get(Document, fix_document_id) is None:
                raise AppError("FIX_DOCUMENT_NOT_FOUND", "关联修复文档不存在", 400)
            case.fix_document_id = fix_document_id
        if fix_config_version_id is not None:
            if self.session.get(RetrievalConfigVersion, fix_config_version_id) is None:
                raise AppError("FIX_CONFIG_NOT_FOUND", "关联检索配置版本不存在", 400)
            case.fix_config_version_id = fix_config_version_id
        if status is not None:
            target = self._validate_status(status)
            if target != case.status:
                allowed = ALLOWED_TRANSITIONS.get(case.status.value, set())
                if target.value not in allowed:
                    raise AppError(
                        "INVALID_FEEDBACK_TRANSITION",
                        f"不允许从 {case.status.value} 流转到 {target.value}", 409,
                        {"from": case.status.value, "to": target.value, "allowed": sorted(allowed)},
                    )
                case.status = target
                if target == FeedbackCaseStatus.PROCESSING:
                    case.first_handled_at = case.first_handled_at or datetime.now(UTC)
                if target in (FeedbackCaseStatus.RESOLVED, FeedbackCaseStatus.IGNORED):
                    case.resolved_at = datetime.now(UTC)
                if target != FeedbackCaseStatus.RESOLVED:
                    case.resolved_at = None
                self._add_event(
                    case, "STATUS_CHANGED", actor=actor, from_status=previous_status,
                    to_status=target.value, note=note,
                )
        self.session.commit()
        self.session.refresh(case)
        return case

    def mark_wait_verify_for_documents(
        self, document_ids: list[uuid.UUID], *, chunk_ids: list[uuid.UUID] | None = None,
        config_version_id: uuid.UUID | None = None, reason: str = "document_changed",
    ) -> int:
        """文档/片段/配置变化后，把相关历史负反馈置为等待复验，返回受影响工单数。"""
        if not document_ids and not chunk_ids and config_version_id is None:
            return 0
        feedbacks = self.session.scalars(
            select(AnswerFeedback).where(AnswerFeedback.rating != FeedbackRating.UP)
        ).all()
        document_set = {str(item) for item in document_ids}
        chunk_set = {str(item) for item in chunk_ids or []}
        changed = 0
        for feedback in feedbacks:
            case = self.session.scalar(select(FeedbackCase).where(
                FeedbackCase.feedback_id == feedback.id
            ))
            if case is None or case.status not in (
                FeedbackCaseStatus.PENDING, FeedbackCaseStatus.PROCESSING, FeedbackCaseStatus.RESOLVED,
            ):
                continue
            related = bool(document_set & set(feedback.document_ids or []))
            if not related and chunk_set:
                related = bool(chunk_set & set(feedback.chunk_ids or []))
            if not related and config_version_id is not None:
                related = feedback.retrieval_config_version_id == config_version_id
            if not related:
                continue
            previous = case.status.value
            case.status = FeedbackCaseStatus.WAIT_VERIFY
            case.resolved_at = None
            self._add_event(
                case, "REVERIFY_TRIGGERED", actor=None, from_status=previous,
                to_status=FeedbackCaseStatus.WAIT_VERIFY.value,
                note="关联资料或检索配置已变更，等待复验",
                detail={"reason": reason, "document_ids": sorted(document_set)},
            )
            changed += 1
        if changed:
            self.session.commit()
        return changed

    # ------------------------------------------------------------ 查询

    def list_mine(self, user: User, page: int = 1, page_size: int = 50) -> tuple[list[dict], int]:
        return self._list_feedback(user, own_only=True, page=page, page_size=page_size)

    def list_cases(
        self, *, statuses: list[str] | None = None, feedback_type: str | None = None,
        knowledge_base_id: uuid.UUID | None = None, assistant_id: uuid.UUID | None = None,
        assignee_id: uuid.UUID | None = None, keyword: str | None = None,
        created_from: datetime | None = None, created_to: datetime | None = None,
        page: int = 1, page_size: int = 50,
    ) -> tuple[list[dict], int]:
        statement = select(FeedbackCase, AnswerFeedback).join(
            AnswerFeedback, FeedbackCase.feedback_id == AnswerFeedback.id
        )
        filters = []
        if statuses:
            filters.append(FeedbackCase.status.in_([self._validate_status(item) for item in statuses]))
        if feedback_type:
            filters.append(AnswerFeedback.feedback_type == FeedbackType(feedback_type))
        if knowledge_base_id is not None:
            filters.append(AnswerFeedback.knowledge_base_ids.contains([str(knowledge_base_id)]))
        if assistant_id is not None:
            filters.append(AnswerFeedback.assistant_id == assistant_id)
        if assignee_id is not None:
            filters.append(FeedbackCase.assignee_id == assignee_id)
        if created_from is not None:
            filters.append(FeedbackCase.created_at >= created_from)
        if created_to is not None:
            filters.append(FeedbackCase.created_at <= created_to)
        if keyword:
            token = f"%{keyword.strip()}%"
            filters.append(or_(
                AnswerFeedback.question_snapshot.ilike(token),
                AnswerFeedback.answer_snapshot.ilike(token),
                AnswerFeedback.comment.ilike(token),
            ))
        total = self.session.scalar(
            select(func.count()).select_from(FeedbackCase)
            .join(AnswerFeedback, FeedbackCase.feedback_id == AnswerFeedback.id)
            .where(*filters)
        ) or 0
        rows = self.session.execute(
            statement.where(*filters)
            .order_by(FeedbackCase.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ).all()
        usernames = self._usernames([feedback.user_id for _, feedback in rows])
        items = [
            self.case_summary(case, feedback, usernames.get(feedback.user_id))
            for case, feedback in rows
        ]
        return items, total

    def case_summary(self, case: FeedbackCase, feedback: AnswerFeedback, username: str | None = None) -> dict:
        return {
            "id": case.id, "feedback_id": feedback.id, "status": case.status.value,
            "priority": case.priority.value, "assignee_id": case.assignee_id,
            "created_at": case.created_at, "updated_at": case.updated_at,
            "resolved_at": case.resolved_at, "first_handled_at": case.first_handled_at,
            "last_verification_result": (
                case.last_verification_result.value if case.last_verification_result else None
            ),
            "question": feedback.question_snapshot,
            "feedback_type": feedback.feedback_type.value,
            "rating": feedback.rating.value,
            "reasons": list(feedback.reasons or []),
            "comment": feedback.comment,
            "user_id": feedback.user_id, "username": username,
            "assistant_id": feedback.assistant_id,
            "knowledge_base_ids": list(feedback.knowledge_base_ids or []),
            "answer_preview": (feedback.answer_snapshot or "")[:200],
        }

    def case_detail(self, case_id: uuid.UUID) -> dict:
        case = self.get_case(case_id)
        feedback = self.session.get(AnswerFeedback, case.feedback_id)
        if feedback is None:
            raise AppError("FEEDBACK_NOT_FOUND", "反馈不存在", 404)
        chat_session = self.session.get(ChatSession, feedback.chat_session_id) if feedback.chat_session_id else None
        assistant = self.session.get(Assistant, feedback.assistant_id) if feedback.assistant_id else None
        sources = self.session.scalars(
            select(ChatMessageSource).where(ChatMessageSource.message_id == feedback.message_id)
            .order_by(ChatMessageSource.citation_number)
        ).all()
        feedback_versions = {
            str(item.get("document_id")): item.get("version_number")
            for item in (feedback.document_versions or [])
        }
        documents = []
        for source in sources:
            document = self.session.get(Document, source.document_id)
            documents.append({
                "document_id": source.document_id,
                "document_name": source.document_name,
                "chunk_id": source.chunk_id,
                "citation_number": source.citation_number,
                "score": source.score,
                "content_snapshot": source.content_snapshot,
                "feedback_version": feedback_versions.get(str(source.document_id)),
                "current_version": document.version_number if document else None,
                "deleted": bool(document.deleted_at) if document else True,
                "enabled": document.enabled if document else False,
                "status": document.status.value if document else None,
            })
        events = self.session.scalars(
            select(FeedbackCaseEvent).where(FeedbackCaseEvent.case_id == case.id)
            .order_by(FeedbackCaseEvent.created_at)
        ).all()
        verifications = self.session.scalars(
            select(FeedbackVerificationRun).where(FeedbackVerificationRun.case_id == case.id)
            .order_by(FeedbackVerificationRun.created_at.desc())
        ).all()
        username = self._usernames([feedback.user_id]).get(feedback.user_id)
        assignee_name = self._usernames([case.assignee_id]).get(case.assignee_id)
        detail = self.case_summary(case, feedback, username)
        detail.update({
            "admin_note": case.admin_note, "conclusion": case.conclusion,
            "fix_document_id": case.fix_document_id, "fix_config_version_id": case.fix_config_version_id,
            "assignee_name": assignee_name,
            "message_id": feedback.message_id, "session_id": feedback.chat_session_id,
            "session_title": chat_session.title if chat_session else None,
            "assistant_name": assistant.name if assistant else None,
            "answer_snapshot": feedback.answer_snapshot,
            "knowledge_scope": feedback.knowledge_scope,
            "retrieval_config_version_id": feedback.retrieval_config_version_id,
            "answer_model": feedback.answer_model, "answer_provider": feedback.answer_provider,
            "documents": documents,
            "events": [{
                "id": event.id, "event_type": event.event_type,
                "from_status": event.from_status, "to_status": event.to_status,
                "actor_id": event.actor_id, "note": event.note, "detail": event.detail,
                "created_at": event.created_at,
            } for event in events],
            "verifications": [self._verification_payload(run) for run in verifications],
        })
        return detail

    def feedback_payload(self, feedback: AnswerFeedback) -> dict:
        sources = self.session.scalars(
            select(ChatMessageSource).where(ChatMessageSource.message_id == feedback.message_id)
            .order_by(ChatMessageSource.citation_number)
        ).all()
        username = self._usernames([feedback.user_id]).get(feedback.user_id)
        assistant = self.session.get(Assistant, feedback.assistant_id) if feedback.assistant_id else None
        case = self.session.scalar(select(FeedbackCase).where(FeedbackCase.feedback_id == feedback.id))
        return {
            "id": feedback.id, "message_id": feedback.message_id,
            "session_id": feedback.chat_session_id,
            "user_id": feedback.user_id, "username": username,
            "rating": feedback.rating.value, "feedback_type": feedback.feedback_type.value,
            "reasons": list(feedback.reasons or []), "comment": feedback.comment,
            "question": feedback.question_snapshot, "answer_content": feedback.answer_snapshot or "",
            "assistant_id": feedback.assistant_id, "assistant_name": assistant.name if assistant else None,
            "knowledge_scope": feedback.knowledge_scope,
            "knowledge_base_ids": list(feedback.knowledge_base_ids or []),
            "retrieval_config_version_id": feedback.retrieval_config_version_id,
            "provider": feedback.answer_provider, "answer_model": feedback.answer_model,
            "sources": [{
                "document_id": source.document_id, "document_name": source.document_name,
                "chunk_id": source.chunk_id, "citation_number": source.citation_number,
                "score": source.score,
            } for source in sources],
            "no_answer": not sources or feedback.knowledge_scope == "NONE",
            "case_id": case.id if case else None,
            "case_status": case.status.value if case else None,
            "created_at": feedback.created_at, "updated_at": feedback.updated_at,
            "resolved_at": feedback.resolved_at, "resolved_by": feedback.resolved_by,
            "resolution_note": feedback.resolution_note,
        }

    # ------------------------------------------------------------ 统计

    def statistics(
        self, *, knowledge_base_id: uuid.UUID | None = None,
        assistant_id: uuid.UUID | None = None, config_version_id: uuid.UUID | None = None,
        created_from: datetime | None = None, created_to: datetime | None = None,
    ) -> dict:
        feedbacks = list(self.session.scalars(select(AnswerFeedback)))
        cases = {case.feedback_id: case for case in self.session.scalars(select(FeedbackCase))}
        filtered = [
            item for item in feedbacks
            if self._matches_stat_filter(item, knowledge_base_id, assistant_id, config_version_id,
                                         created_from, created_to)
        ]
        return {
            "overall": self._aggregate_statistics(filtered, cases),
            "knowledge_bases": self._dimension_by_knowledge_base(filtered, cases),
            "assistants": self._dimension_by_assistant(filtered, cases),
            "config_versions": self._dimension_by_config_version(filtered, cases),
        }

    @staticmethod
    def _matches_stat_filter(
        feedback, knowledge_base_id, assistant_id, config_version_id, created_from, created_to,
    ) -> bool:
        if knowledge_base_id is not None and str(knowledge_base_id) not in (feedback.knowledge_base_ids or []):
            return False
        if assistant_id is not None and feedback.assistant_id != assistant_id:
            return False
        if config_version_id is not None and feedback.retrieval_config_version_id != config_version_id:
            return False
        if created_from is not None and feedback.created_at and feedback.created_at < created_from:
            return False
        if created_to is not None and feedback.created_at and feedback.created_at > created_to:
            return False
        return True

    def _aggregate_statistics(self, feedbacks: list[AnswerFeedback], cases: dict) -> dict:
        up = sum(1 for item in feedbacks if item.rating == FeedbackRating.UP)
        down = sum(1 for item in feedbacks if item.rating == FeedbackRating.DOWN)
        report = sum(1 for item in feedbacks if item.feedback_type == FeedbackType.REPORT)
        no_answer = sum(1 for item in feedbacks if not item.chunk_ids)
        pending = sum(
            1 for item in feedbacks
            if cases.get(item.id) is not None and cases[item.id].status == FeedbackCaseStatus.PENDING
        )
        explicit = up + down + report
        handled = [cases[item.id] for item in feedbacks if cases.get(item.id) is not None]
        resolved = [case for case in handled if case.status == FeedbackCaseStatus.RESOLVED]
        durations = [
            (case.resolved_at - (case.first_handled_at or case.created_at)).total_seconds() / 3600
            for case in handled
            if case.resolved_at and (case.first_handled_at or case.created_at)
        ]
        verifications = list(self.session.scalars(select(FeedbackVerificationRun)))
        passed = sum(1 for run in verifications if run.status.value == "PASSED")
        failed = sum(1 for run in verifications if run.status.value == "FAILED")
        return {
            "feedback_count": len(feedbacks),
            "helpful_count": up,
            "unhelpful_count": down + report,
            "report_count": report,
            "no_answer_count": no_answer,
            "explicit_feedback_count": explicit,
            "satisfaction_rate": round(up / explicit, 4) if explicit else None,
            "no_answer_rate": round(no_answer / len(feedbacks), 4) if feedbacks else None,
            "pending_count": pending,
            "resolved_count": len(resolved),
            "ignored_count": sum(1 for case in handled if case.status == FeedbackCaseStatus.IGNORED),
            "avg_handling_hours": round(sum(durations) / len(durations), 2) if durations else None,
            "verification_pass_rate": round(passed / (passed + failed), 4) if (passed + failed) else None,
        }

    def _dimension_by_knowledge_base(self, feedbacks: list[AnswerFeedback], cases: dict) -> list[dict]:
        buckets: dict[str, list[AnswerFeedback]] = {}
        for item in feedbacks:
            for kb_id in item.knowledge_base_ids or []:
                buckets.setdefault(str(kb_id), []).append(item)
        names = {
            str(row[0]): row[1]
            for row in self.session.execute(
                select(KnowledgeBase.id, KnowledgeBase.name)
            ).all()
        }
        return [
            {"knowledge_base_id": kb_id, "knowledge_base_name": names.get(kb_id), **self._aggregate_statistics(items, cases)}
            for kb_id, items in sorted(buckets.items(), key=lambda pair: -len(pair[1]))
        ]

    def _dimension_by_assistant(self, feedbacks: list[AnswerFeedback], cases: dict) -> list[dict]:
        buckets: dict[str, list[AnswerFeedback]] = {}
        for item in feedbacks:
            if item.assistant_id is not None:
                buckets.setdefault(str(item.assistant_id), []).append(item)
        names = {
            str(row[0]): row[1]
            for row in self.session.execute(select(Assistant.id, Assistant.name)).all()
        }
        return [
            {"assistant_id": assistant_id, "assistant_name": names.get(assistant_id), **self._aggregate_statistics(items, cases)}
            for assistant_id, items in sorted(buckets.items(), key=lambda pair: -len(pair[1]))
        ]

    def _dimension_by_config_version(self, feedbacks: list[AnswerFeedback], cases: dict) -> list[dict]:
        buckets: dict[str, list[AnswerFeedback]] = {}
        for item in feedbacks:
            if item.retrieval_config_version_id is not None:
                buckets.setdefault(str(item.retrieval_config_version_id), []).append(item)
        names = {
            str(row[0]): row[1]
            for row in self.session.execute(
                select(RetrievalConfigVersion.id, RetrievalConfigVersion.name)
            ).all()
        }
        return [
            {"config_version_id": config_id, "config_version_name": names.get(config_id),
             **self._aggregate_statistics(items, cases)}
            for config_id, items in sorted(buckets.items(), key=lambda pair: -len(pair[1]))
        ]

    # ------------------------------------------------------------ 内部工具

    def _list_feedback(
        self, user: User, *, own_only: bool, page: int, page_size: int,
    ) -> tuple[list[dict], int]:
        statement = select(AnswerFeedback)
        filters = []
        if own_only or not user.is_super_admin:
            filters.append(AnswerFeedback.user_id == user.id)
        total = self.session.scalar(
            select(func.count()).select_from(AnswerFeedback).where(*filters)
        ) or 0
        rows = self.session.scalars(
            statement.where(*filters).order_by(AnswerFeedback.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ).all()
        return [self.feedback_payload(item) for item in rows], total

    def _find_message(self, message_id: uuid.UUID) -> ChatMessage:
        message = self.session.scalar(select(ChatMessage).where(
            ChatMessage.id == message_id, ChatMessage.role == ChatMessageRole.ASSISTANT,
        ))
        if message is None:
            raise AppError("MESSAGE_NOT_FOUND", "回答消息不存在", 404)
        return message

    def _require_own(self, message: ChatMessage, user: User) -> None:
        if user.is_super_admin:
            return
        chat_session = self.session.scalar(select(ChatSession).where(ChatSession.id == message.session_id))
        if chat_session is None or chat_session.user_id != user.id:
            raise AppError("FEEDBACK_FORBIDDEN", "不能评价他人的回答", 403)

    def _sources(self, message_id: uuid.UUID) -> list[ChatMessageSource]:
        return list(self.session.scalars(
            select(ChatMessageSource).where(ChatMessageSource.message_id == message_id)
            .order_by(ChatMessageSource.citation_number)
        ))

    def _question_for(self, message: ChatMessage) -> str | None:
        return self.session.scalar(
            select(ChatMessage.content).where(
                ChatMessage.session_id == message.session_id,
                ChatMessage.role == ChatMessageRole.USER,
                ChatMessage.created_at <= message.created_at,
            ).order_by(ChatMessage.created_at.desc()).limit(1)
        )

    def _active_config_version_id(self) -> uuid.UUID | None:
        return self.session.scalar(
            select(RetrievalConfigVersion.id).where(RetrievalConfigVersion.is_default.is_(True)).limit(1)
        )

    @staticmethod
    def _answer_model(message: ChatMessage) -> str | None:
        metrics = message.metrics or {}
        return metrics.get("model") or metrics.get("llm_model")

    def _usernames(self, user_ids: list) -> dict:
        clean = [item for item in user_ids if item is not None]
        if not clean:
            return {}
        return dict(self.session.execute(select(User.id, User.username).where(User.id.in_(clean))).all())

    @staticmethod
    def _validate_status(status: str) -> FeedbackCaseStatus:
        try:
            return FeedbackCaseStatus(status)
        except ValueError as exc:
            raise AppError(
                "INVALID_FEEDBACK_STATUS", f"反馈状态不合法：{status}", 400,
                {"allowed": CASE_STATUS_VALUES},
            ) from exc

    @staticmethod
    def _validate_priority(priority: str) -> FeedbackPriority:
        try:
            return FeedbackPriority(priority)
        except ValueError as exc:
            raise AppError(
                "INVALID_FEEDBACK_PRIORITY", f"反馈优先级不合法：{priority}", 400,
                {"allowed": CASE_PRIORITY_VALUES},
            ) from exc

    @staticmethod
    def _verification_payload(run: FeedbackVerificationRun) -> dict:
        return {
            "id": run.id, "status": run.status.value, "question": run.question,
            "before_answer": run.before_answer, "before_sources": run.before_sources,
            "before_config_version_id": run.before_config_version_id,
            "after_answer": run.after_answer, "after_sources": run.after_sources,
            "after_config_version_id": run.after_config_version_id,
            "after_message_id": run.after_message_id,
            "base_score": run.base_score, "final_score": run.final_score,
            "no_answer": run.no_answer, "duration_ms": run.duration_ms,
            "admin_conclusion": run.admin_conclusion, "error_message": run.error_message,
            "created_at": run.created_at, "completed_at": run.completed_at,
        }
