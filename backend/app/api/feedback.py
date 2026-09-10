"""答案反馈 API：收集、筛选与处理闭环。"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import AppError
from app.models import (
    AnswerFeedback, Assistant, ChatMessage, ChatMessageRole, ChatMessageSource,
    ChatMessageStatus, ChatProvider, FeedbackRating,
)
from app.models.chat import ChatSession
from app.services.audit import record as audit_record
from app.services.feedback_ranking import FeedbackRankingService

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

DOWN_REASONS = [
    "答非所问", "内容不准确", "引用不正确", "资料已经过期",
    "回答不完整", "没有找到已有资料", "回答速度太慢",
]


def _find_message(session: Session, message_id: uuid.UUID) -> ChatMessage:
    message = session.scalar(select(ChatMessage).where(
        ChatMessage.id == message_id, ChatMessage.role == ChatMessageRole.ASSISTANT,
    ))
    if message is None:
        raise AppError("MESSAGE_NOT_FOUND", "回答消息不存在", 404)
    return message


def _own_session_user(session: Session, message: ChatMessage, user) -> bool:
    if user is None:
        return False
    if user.is_super_admin:
        return True
    session_row = session.scalar(select(ChatSession).where(ChatSession.id == message.session_id))
    return bool(session_row and session_row.user_id == user.id)


class FeedbackCreate(BaseModel):
    message_id: uuid.UUID
    rating: str = Field(pattern="^(UP|DOWN)$")
    reasons: list[str] = Field(default_factory=list, max_length=8)
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    session_id: uuid.UUID | None
    session_title: str | None
    user_id: uuid.UUID | None
    username: str | None
    rating: str
    reasons: list[str]
    comment: str | None
    question: str | None
    answer_content: str
    sources: list[dict] = Field(default_factory=list)
    assistant_id: uuid.UUID | None
    assistant_name: str | None
    provider: str | None
    knowledge_scope: str | None
    metrics: dict = Field(default_factory=dict)
    no_answer: bool = False
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: uuid.UUID | None
    resolution_note: str | None


class FeedbackListResponse(BaseModel):
    items: list[FeedbackOut]
    page: int
    page_size: int
    total: int


def _question_for(session: Session, message: ChatMessage) -> str | None:
    row = session.scalar(
        select(ChatMessage.content).where(
            ChatMessage.session_id == message.session_id,
            ChatMessage.role == ChatMessageRole.USER,
            ChatMessage.created_at <= message.created_at,
        ).order_by(ChatMessage.created_at.desc()).limit(1)
    )
    return row


def _payload(session: Session, feedback: AnswerFeedback, message: ChatMessage, username: str | None = None) -> FeedbackOut:
    chat_session = session.get(ChatSession, message.session_id)
    sources = session.scalars(
        select(ChatMessageSource).where(ChatMessageSource.message_id == feedback.message_id)
        .order_by(ChatMessageSource.citation_number)
    ).all()
    assistant_name = None
    if chat_session is not None and chat_session.assistant_id is not None:
        assistant = session.get(Assistant, chat_session.assistant_id)
        assistant_name = assistant.name if assistant else None
    no_answer = not sources or message.knowledge_scope == "NONE"
    return FeedbackOut(
        id=feedback.id, message_id=feedback.message_id,
        session_id=message.session_id, session_title=chat_session.title if chat_session else None,
        user_id=feedback.user_id, username=username, rating=feedback.rating.value,
        reasons=list(feedback.reasons or []), comment=feedback.comment,
        question=_question_for(session, message), answer_content=message.content,
        sources=[{
            "document_id": source.document_id, "document_name": source.document_name,
            "citation_number": source.citation_number,
        } for source in sources],
        assistant_id=chat_session.assistant_id if chat_session else None,
        assistant_name=assistant_name,
        provider=message.provider.value if message.provider else None,
        knowledge_scope=message.knowledge_scope,
        metrics=message.metrics or {}, no_answer=no_answer,
        created_at=feedback.created_at, resolved_at=feedback.resolved_at,
        resolved_by=feedback.resolved_by, resolution_note=feedback.resolution_note,
    )


def _feedbacks(
    session: Session, user, own_only: bool = False, *, rating: str | None = None,
    resolved: bool | None = None, assistant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None, username: str | None = None,
    created_from: datetime | None = None, created_to: datetime | None = None,
    no_answer: bool | None = None, document_id: uuid.UUID | None = None,
    reason: str | None = None, page: int = 1, page_size: int = 50,
) -> tuple[list[FeedbackOut], int]:
    if user is None:
        raise AppError("AUTH_REQUIRED", "请先登录", 401)
    statement = select(AnswerFeedback, ChatMessage).join(
        ChatMessage, AnswerFeedback.message_id == ChatMessage.id
    )
    filters = []
    if own_only or not user.is_super_admin:
        filters.append(AnswerFeedback.user_id == user.id)
    if rating:
        filters.append(AnswerFeedback.rating == FeedbackRating(rating))
    if resolved is not None:
        filters.append(AnswerFeedback.resolved_at.is_not(None) if resolved else AnswerFeedback.resolved_at.is_(None))
    if assistant_id is not None:
        filters.append(ChatMessage.session_id.in_(
            select(ChatSession.id).where(ChatSession.assistant_id == assistant_id)
        ))
    if user_id is not None:
        filters.append(AnswerFeedback.user_id == user_id)
    if username:
        from app.models import User

        filters.append(AnswerFeedback.user_id.in_(
            select(User.id).where(User.username.ilike(f"%{username.strip()}%"))
        ))
    if created_from is not None:
        filters.append(AnswerFeedback.created_at >= created_from)
    if created_to is not None:
        filters.append(AnswerFeedback.created_at <= created_to)
    if document_id is not None:
        filters.append(AnswerFeedback.document_id == document_id)
    if reason:
        filters.append(AnswerFeedback.reasons.contains([reason]))
    if no_answer is not None:
        has_sources = select(ChatMessageSource.message_id)
        if no_answer:
            filters.append(or_(
                ~ChatMessage.id.in_(has_sources),
                ChatMessage.knowledge_scope == "NONE",
            ))
        else:
            filters.append(and_(
                ChatMessage.id.in_(has_sources),
                or_(ChatMessage.knowledge_scope.is_(None), ChatMessage.knowledge_scope != "NONE"),
            ))
    total = session.scalar(
        select(func.count()).select_from(AnswerFeedback)
        .join(ChatMessage, AnswerFeedback.message_id == ChatMessage.id)
        .where(*filters)
    ) or 0
    rows = session.execute(
        statement.where(*filters).order_by(AnswerFeedback.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    user_ids = [feedback.user_id for feedback, _ in rows if feedback.user_id]
    usernames: dict = {}
    if user_ids:
        from app.models import User

        usernames = dict(session.execute(select(User.id, User.username).where(User.id.in_(user_ids))).all())
    return [
        _payload(session, feedback, message, usernames.get(feedback.user_id))
        for feedback, message in rows
    ], total


class ResolveBody(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


@router.post("", status_code=201)
def create_feedback(
    body: FeedbackCreate,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    """提交对一条回答的点赞/点踩反馈。"""
    user = getattr(request.state, "auth_user", None)
    if user is None:
        raise AppError("AUTH_REQUIRED", "请先登录", 401)
    message = _find_message(session, body.message_id)
    if not _own_session_user(session, message, user):
        raise AppError("FEEDBACK_FORBIDDEN", "不能评价他人的回答", 403)
    source_document_ids = list(session.scalars(
        select(ChatMessageSource.document_id).where(ChatMessageSource.message_id == body.message_id).distinct()
    ).all())
    document_id = source_document_ids[0] if len(source_document_ids) == 1 else None
    existing = session.scalar(select(AnswerFeedback).where(
        AnswerFeedback.message_id == body.message_id, AnswerFeedback.user_id == user.id,
    ))
    rating = FeedbackRating(body.rating)
    if existing:
        existing.rating = rating
        existing.reasons = list(body.reasons)
        existing.comment = body.comment
        existing.document_id = document_id
        existing.resolved_at = None
        existing.resolution_note = None
        feedback = existing
    else:
        feedback = AnswerFeedback(
            message_id=body.message_id, user_id=user.id, rating=rating,
            reasons=list(body.reasons), comment=body.comment, document_id=document_id,
        )
        session.add(feedback)
    session.commit()
    if document_id is not None:
        FeedbackRankingService(session, request.app.state.settings).recompute(document_id)
    return {"ok": True}


@router.get("", response_model=FeedbackListResponse)
def list_feedback(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    rating: str | None = None,
    resolved: bool | None = None,
    assistant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    username: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    no_answer: bool | None = None,
    document_id: uuid.UUID | None = None,
    reason: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> FeedbackListResponse:
    user = getattr(request.state, "auth_user", None)
    items, total = _feedbacks(
        session, user, own_only=False, rating=rating, resolved=resolved,
        assistant_id=assistant_id, user_id=user_id, username=username,
        created_from=created_from, created_to=created_to, no_answer=no_answer,
        document_id=document_id, reason=reason, page=page, page_size=page_size,
    )
    return FeedbackListResponse(items=items, page=page, page_size=page_size, total=total)


@router.get("/mine", response_model=FeedbackListResponse)
def list_my_feedback(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> FeedbackListResponse:
    user = getattr(request.state, "auth_user", None)
    items, total = _feedbacks(session, user, own_only=True, page=page, page_size=page_size)
    return FeedbackListResponse(items=items, page=page, page_size=page_size, total=total)


@router.get("/reasons")
def list_reasons(request: Request) -> dict:
    getattr(request.state, "auth_user", None)
    return {"items": DOWN_REASONS}


@router.get("/statistics")
def feedback_statistics(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    user = getattr(request.state, "auth_user", None)
    if user is None or not user.is_super_admin:
        raise AppError("ADMIN_REQUIRED", "需要管理员权限", 403)
    service = FeedbackRankingService(session, request.app.state.settings)
    return {
        "enabled": service.enabled,
        "min_samples": request.app.state.settings.search_feedback_min_samples,
        "max_boost": request.app.state.settings.search_feedback_max_boost,
        "items": service.statistics(),
    }


@router.patch("/{feedback_id}/resolve")
def resolve_feedback(
    feedback_id: uuid.UUID,
    body: ResolveBody,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    """管理员标记反馈已处理并记录说明。"""
    user = getattr(request.state, "auth_user", None)
    if user is None or not user.is_super_admin:
        raise AppError("ADMIN_REQUIRED", "需要管理员权限", 403)
    feedback = session.get(AnswerFeedback, feedback_id)
    if feedback is None:
        raise AppError("FEEDBACK_NOT_FOUND", "反馈不存在", 404)
    feedback.resolved_at = datetime.now(UTC)
    feedback.resolved_by = user.id
    feedback.resolution_note = body.note
    session.commit()
    audit_record(session, "feedback_resolved", user=user, target_type="feedback", target_id=feedback.id)
    return {"ok": True}
