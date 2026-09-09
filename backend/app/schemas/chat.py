"""聊天会话、消息、来源快照与引用当前状态的请求/响应契约。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.chat import ChatMessageRole, ChatMessageStatus, ChatProvider


class ChatSourceSnapshot(BaseModel):
    """历史引用快照；即使文档后来被删除或停用，内容仍从快照读出。"""
    id: uuid.UUID
    citation_number: int
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    document_name: str
    content_snapshot: str
    location_snapshot: dict
    score: float | None = None
    available: bool
    status: str  # ACTIVE / DISABLED / DELETED


class ChatMessageOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: ChatMessageRole
    content: str
    provider: ChatProvider | None
    knowledge_scope: str | None
    status: ChatMessageStatus
    error_code: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    metrics: dict = Field(default_factory=dict)
    sources: list[ChatSourceSnapshot] = Field(default_factory=list)


class ChatSessionBase(BaseModel):
    id: uuid.UUID
    title: str
    assistant_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None
    archived_at: datetime | None


class ChatSessionListItem(ChatSessionBase):
    message_count: int = 0
    last_preview: str | None = None


class ChatSessionDetail(ChatSessionBase):
    messages: list[ChatMessageOut] = Field(default_factory=list)


class ChatSessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    assistant_id: uuid.UUID | None = None


class ChatSessionPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)


class ChatSessionListResponse(BaseModel):
    items: list[ChatSessionListItem]
    total: int
