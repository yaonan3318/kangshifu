"""答案反馈 API：用户提交、修改与查询自己的反馈。

管理侧的处理队列在 ``app/api/feedback_admin.py``，两者共用 ``FeedbackService``。
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.services.audit import audit_action
from app.services.feedback import FeedbackService
from app.services.rbac import require_permission

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

ANSWER_USE = "ANSWER_USE"

DOWN_REASONS = [
    "答非所问", "内容不准确", "引用不正确", "资料已经过期",
    "回答不完整", "没有找到已有资料", "回答速度太慢",
    "缺失知识", "资料不足", "举报敏感或错误内容",
]


class FeedbackCreate(BaseModel):
    message_id: uuid.UUID
    rating: str = Field(pattern="^(UP|DOWN|REPORT)$")
    feedback_type: str | None = Field(default=None, pattern="^(UP|DOWN|REPORT)$")
    reasons: list[str] = Field(default_factory=list, max_length=8)
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackListResponse(BaseModel):
    items: list[dict]
    page: int
    page_size: int
    total: int


@router.post("", status_code=201)
def create_feedback(
    body: FeedbackCreate,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """提交或覆盖对一条回答的反馈；同一用户同一回答只保留一条有效记录。"""
    user = require_permission(current_user(request), ANSWER_USE)
    service = FeedbackService(session, settings)
    with audit_action(
        session, "feedback_submitted", user=user, target_type="feedback",
    ) as audit:
        feedback = service.submit(
            user, message_id=body.message_id, rating=body.rating,
            feedback_type=body.feedback_type, reasons=body.reasons, comment=body.comment,
        )
        audit.id = feedback.id
        audit.detail = {"rating": feedback.rating.value, "type": feedback.feedback_type.value}
    return {"ok": True, "id": feedback.id, "rating": feedback.rating.value}


@router.get("/mine", response_model=FeedbackListResponse)
def list_my_feedback(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> FeedbackListResponse:
    user = require_permission(current_user(request), ANSWER_USE)
    items, total = FeedbackService(session, settings).list_mine(user, page=page, page_size=page_size)
    return FeedbackListResponse(items=items, page=page, page_size=page_size, total=total)


@router.get("/reasons")
def list_reasons(request: Request) -> dict:
    current_user(request)
    return {"items": DOWN_REASONS}
