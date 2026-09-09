"""答案反馈 API。"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_session
from app.errors import AppError
from app.models import AnswerFeedback, ChatMessage, ChatMessageRole, ChatMessageStatus, FeedbackRating
from app.models.chat import ChatSession
from app.services.audit import record as audit_record

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
    session_title: str | None
    user_id: uuid.UUID | None
    username: str | None
    rating: str
    reasons: list[str]
    comment: str | None
    answer_content: str
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: uuid.UUID | None
    resolution_note: str | None


class FeedbackListResponse(BaseModel):
    items: list[FeedbackOut]
    page: int
    page_size: int
    total: int


def _payload(session: Session, feedback: AnswerFeedback, username: str | None = None) -> FeedbackOut:
    message = session.scalar(select(ChatMessage).where(ChatMessage.id == feedback.message_id))
    session_title = None
    if message is not None:
        chat_session = session.get(ChatSession, message.session_id)
        session_title = chat_session.title if chat_session else None
    return FeedbackOut(
        id=feedback.id, message_id=feedback.message_id, session_title=session_title,
        user_id=feedback.user_id, username=username, rating=feedback.rating.value,
        reasons=list(feedback.reasons or []), comment=feedback.comment,
        answer_content=message.content if message else "",
        created_at=feedback.created_at, resolved_at=feedback.resolved_at,
        resolved_by=feedback.resolved_by, resolution_note=feedback.resolution_note,
    )


def _feedbacks(
    session: Session, user, own_only: bool, resolved: bool | None = None,
    page: int = 1, page_size: int = 50,
) -> tuple[list[FeedbackOut], int]:
    if user is None:
        raise AppError("AUTH_REQUIRED", "请先登录", 401)
    statement = select(AnswerFeedback).options(selectinload(AnswerFeedback.message))
    filters = []
    if own_only or not user.is_super_admin:
        filters.append(AnswerFeedback.user_id == user.id)
    if resolved is not None:
        if resolved:
            filters.append(AnswerFeedback.resolved_at.is_not(None))
        else:
            filters.append(AnswerFeedback.resolved_at.is_(None))
    total = session.scalar(select(func.count()).select_from(AnswerFeedback).where(*filters)) or 0
    rows = session.scalars(
        statement.where(*filters).order_by(AnswerFeedback.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    usernames = {}
    user_ids = [item.user_id for item in rows if item.user_id]
    if user_ids:
        from app.models import User

        usernames = dict(session.execute(select(User.id, User.username).where(User.id.in_(user_ids))).all())
    return [_payload(session, item, usernames.get(item.user_id)) for item in rows], total


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
    existing = session.scalar(select(AnswerFeedback).where(
        AnswerFeedback.message_id == body.message_id, AnswerFeedback.user_id == user.id,
    ))
    rating = FeedbackRating(body.rating)
    if existing:
        existing.rating = rating
        existing.reasons = list(body.reasons)
        existing.comment = body.comment
        existing.resolved_at = None
        existing.resolution_note = None
        feedback = existing
    else:
        feedback = AnswerFeedback(
            message_id=body.message_id, user_id=user.id, rating=rating,
            reasons=list(body.reasons), comment=body.comment,
        )
        session.add(feedback)
    session.commit()
    return {"ok": True}


@router.get("", response_model=FeedbackListResponse)
def list_feedback(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    resolved: bool | None = None,
    page: int = 1,
    page_size: int = 50,
) -> FeedbackListResponse:
    user = getattr(request.state, "auth_user", None)
    items, total = _feedbacks(session, user, own_only=False, resolved=resolved, page=page, page_size=page_size)
    return FeedbackListResponse(items=items, page=page, page_size=page_size, total=total)


@router.get("/mine", response_model=FeedbackListResponse)
def list_my_feedback(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    page: int = 1,
    page_size: int = 50,
) -> FeedbackListResponse:
    user = getattr(request.state, "auth_user", None)
    items, total = _feedbacks(session, user, own_only=True, page=page, page_size=page_size)
    return FeedbackListResponse(items=items, page=page, page_size=page_size, total=total)


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
