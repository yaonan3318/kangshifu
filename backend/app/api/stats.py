"""运营统计与单次问答追踪接口（管理员）。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import AppError
from app.models import ChatMessage, ChatMessageRole, ChatMessageSource, ChatSession
from app.services.permissions import require_user
from app.services.rbac import require_permission
from app.services.stats import compute_dashboard, compute_overview

router = APIRouter(prefix="/api/stats", tags=["stats"])

STATS_VIEW = "STATS_VIEW"


def _stats_user(request: Request):
    return require_permission(getattr(request.state, "auth_user", None), STATS_VIEW)


@router.get("/dashboard")
def dashboard(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    """首页/比赛演示数据：仅汇总计数，登录即可查看，不含用户隐私明细。"""
    require_user(getattr(request.state, "auth_user", None))
    return compute_dashboard(session)


@router.get("/overview")
def stats_overview(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    days: int = 7,
) -> dict:
    """返回最近 N 天问答、检索、成功率、反馈与热点统计。"""
    return compute_overview(session, _stats_user(request), days=days)


@router.get("/trace/{message_id}")
def message_trace(
    message_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    """返回单条助手回答的追踪信息：问题、答案、引用快照与阶段耗时。"""
    _stats_user(request)
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
