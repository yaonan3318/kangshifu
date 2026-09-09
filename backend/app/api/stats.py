"""运营统计与单次问答追踪接口（管理员）。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import AppError
from app.models import ChatMessage, ChatMessageRole, ChatMessageSource, ChatSession
from app.services.stats import compute_overview

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _admin(request: Request):
    user = getattr(request.state, "auth_user", None)
    if user is None or not user.is_super_admin:
        raise AppError("ADMIN_REQUIRED", "需要管理员权限", 403)
    return user


@router.get("/overview")
def stats_overview(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    days: int = 7,
) -> dict:
    """返回最近 N 天问答、检索、成功率、反馈与热点统计。"""
    return compute_overview(session, _admin(request), days=days)


@router.get("/trace/{message_id}")
def message_trace(
    message_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    """返回单条助手回答的追踪信息：问题、答案、引用快照与阶段耗时。"""
    _admin(request)
    message = session.get(ChatMessage, message_id)
    if message is None or message.role != ChatMessageRole.ASSISTANT:
        raise AppError("MESSAGE_NOT_FOUND", "回答消息不存在", 404)
    chat_session = session.get(ChatSession, message.session_id)
    user_message = session.scalar(
        select(ChatMessage).where(
            ChatMessage.session_id == message.session_id,
            ChatMessage.role == ChatMessageRole.USER,
            ChatMessage.created_at <= message.created_at,
        ).order_by(ChatMessage.created_at.desc()).limit(1)
    )
    sources = session.scalars(
        select(ChatMessageSource).where(ChatMessageSource.message_id == message.id)
    ).all()
    return {
        "message_id": str(message.id),
        "session_title": chat_session.title if chat_session else None,
        "question": user_message.content if user_message else None,
        "answer": message.content,
        "provider": message.provider.value if message.provider else None,
        "knowledge_scope": message.knowledge_scope,
        "status": message.status.value,
        "metrics": message.metrics or {},
        "sources": [
            {
                "citation_number": item.citation_number, "document_name": item.document_name,
                "document_id": str(item.document_id), "chunk_id": str(item.chunk_id),
                "location": item.location_snapshot, "score": item.score,
            }
            for item in sources
        ],
    }
