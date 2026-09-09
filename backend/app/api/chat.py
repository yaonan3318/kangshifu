"""聊天会话 API：会话生命周期、消息读取与历史引用快照。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import AppError
from app.models import ChatMessage, ChatMessageSource, ChatSession
from app.schemas.chat import (
    ChatMessageOut, ChatSessionCreate, ChatSessionDetail, ChatSessionListItem,
    ChatSessionListResponse, ChatSessionPatch,
)
from app.services.chat import ChatService, default_title_for

router = APIRouter(prefix="/api/chat", tags=["chat"])

DEFAULT_PAGE_SIZE = 50


def get_chat_service(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> ChatService:
    return ChatService(session, user=getattr(request.state, "auth_user", None))


def _source_payload(source: ChatMessageSource, service: ChatService) -> dict:
    hydrated = service.hydrate_source(source)
    hydrated["id"] = source.id
    return hydrated


def _message_payload(message: ChatMessage, service: ChatService) -> ChatMessageOut:
    return ChatMessageOut(
        id=message.id, session_id=message.session_id, role=message.role,
        content=message.content, provider=message.provider,
        knowledge_scope=message.knowledge_scope, status=message.status,
        error_code=message.error_code, error_message=message.error_message,
        created_at=message.created_at, completed_at=message.completed_at,
        metrics=message.metrics or {},
        sources=[_source_payload(source, service) for source in message.sources],
    )


def _session_payload(session_row: ChatSession, service: ChatService) -> ChatSessionDetail:
    messages = service.messages(session_row.id)
    return ChatSessionDetail(
        id=session_row.id, title=session_row.title,
        assistant_id=session_row.assistant_id,
        created_at=session_row.created_at, updated_at=session_row.updated_at,
        last_message_at=session_row.last_message_at,
        archived_at=session_row.archived_at,
        messages=[_message_payload(message, service) for message in messages],
    )


def _list_item_payload(session_row: ChatSession, service: ChatService) -> ChatSessionListItem:
    return ChatSessionListItem(
        id=session_row.id, title=session_row.title,
        assistant_id=session_row.assistant_id,
        created_at=session_row.created_at, updated_at=session_row.updated_at,
        last_message_at=session_row.last_message_at,
        archived_at=session_row.archived_at,
        message_count=service.message_count(session_row.id),
        last_preview=service.last_preview(session_row.id),
    )


def _find(service: ChatService, session_id: uuid.UUID, include_archived: bool = False) -> ChatSession:
    try:
        return service.get(session_id, include_archived=include_archived)
    except KeyError as exc:
        raise AppError("CHAT_SESSION_NOT_FOUND", "会话不存在", 404) from exc


@router.get("/sessions", response_model=ChatSessionListResponse)
def list_sessions(
    service: Annotated[ChatService, Depends(get_chat_service)],
    search: str | None = None,
    archived: bool | None = None,
    page: int = Field(default=1, ge=1),
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
) -> ChatSessionListResponse:
    """按最近更新时间列出会话；可搜索标题、只看回收站/归档。"""
    rows, total = service.list_sessions(
        search=search, archived=archived,
        limit=page_size, offset=(page - 1) * page_size,
    )
    return ChatSessionListResponse(
        items=[_list_item_payload(row, service) for row in rows], total=total,
    )


@router.post("/sessions", response_model=ChatSessionDetail)
def create_session(
    body: ChatSessionCreate,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatSessionDetail:
    """新建会话；标题为空时使用默认“新会话”，首个问题会触发自动命名。"""
    return _session_payload(service.create(body.title, body.assistant_id), service)


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
def get_session_detail(
    session_id: uuid.UUID,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatSessionDetail:
    """读取会话全部消息（含归档）；引用给出快照与当前资料状态。"""
    return _session_payload(_find(service, session_id, include_archived=True), service)


@router.patch("/sessions/{session_id}", response_model=ChatSessionDetail)
def rename_session(
    session_id: uuid.UUID,
    body: ChatSessionPatch,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatSessionDetail:
    """重命名会话标题。"""
    row = _find(service, session_id, include_archived=True)
    if body.title:
        service.rename(row.id, body.title)
    return _session_payload(_find(service, session_id, include_archived=True), service)


@router.post("/sessions/{session_id}/archive", response_model=ChatSessionListItem)
def archive_session(
    session_id: uuid.UUID,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatSessionListItem:
    """归档会话，保留数据但从默认列表隐藏。"""
    return _list_item_payload(service.archive(session_id), service)


@router.post("/sessions/{session_id}/restore", response_model=ChatSessionListItem)
def restore_session(
    session_id: uuid.UUID,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatSessionListItem:
    """把归档会话恢复到默认列表。"""
    return _list_item_payload(service.restore(session_id), service)


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: uuid.UUID,
    service: Annotated[ChatService, Depends(get_chat_service)],
    purge: bool = False,
) -> dict:
    """默认归档会话；purge=true 时连同消息永久删除。"""
    if purge:
        service.purge(session_id)
        return {"deleted": True}
    return {"archived": True}


class SessionCreateFromQuestion(BaseModel):
    """知识问答页在没有活动会话时使用问题创建会话。"""
    question: str = Field(min_length=1, max_length=1000)


@router.post("/sessions/from-question", response_model=ChatSessionDetail)
def create_session_from_question(
    body: SessionCreateFromQuestion,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatSessionDetail:
    """由首个问题创建会话并自动命名，随后把 session_id 交给问答流。"""
    return _session_payload(service.create(default_title_for(body.question)), service)
