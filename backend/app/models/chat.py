"""聊天会话持久化 ORM：会话、消息和回答引用快照，保证切换页面或重启后不丢失。"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ChatMessageRole(str, enum.Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM = "SYSTEM"


class ChatProvider(str, enum.Enum):
    LOCAL = "LOCAL"
    DEEPSEEK = "DEEPSEEK"
    HARNESS = "HARNESS"


class ChatMessageStatus(str, enum.Enum):
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class ChatSession(Base):
    """一次持续对话；用户权限系统完成前 user_id/assistant_id 可以为空。"""
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), default="新会话")
    assistant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    """会话中的一条消息；回答结束后保存来源快照，文档后来修改也不影响历史引用。"""
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[ChatMessageRole] = mapped_column(Enum(ChatMessageRole, native_enum=False), index=True)
    content: Mapped[str] = mapped_column(Text)
    provider: Mapped[ChatProvider | None] = mapped_column(Enum(ChatProvider, native_enum=False), nullable=True)
    knowledge_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[ChatMessageStatus] = mapped_column(
        Enum(ChatMessageStatus, native_enum=False), default=ChatMessageStatus.COMPLETED
    )
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped[ChatSession] = relationship(back_populates="messages")
    sources: Mapped[list["ChatMessageSource"]] = relationship(back_populates="message", cascade="all, delete-orphan")


class ChatMessageSource(Base):
    """回答引用片段的快照；资料即使被删除或停用，历史引用仍可展示。"""
    __tablename__ = "chat_message_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    citation_number: Mapped[int] = mapped_column(Integer)
    document_name: Mapped[str] = mapped_column(String(1024))
    content_snapshot: Mapped[str] = mapped_column(Text)
    location_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 检索日志：召回排名与精排前后排名，便于追溯排序变化。
    retrieval_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pre_rerank_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    post_rerank_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # P2-2：回答时引用的文档版本，用于判断“版本已更新”。
    document_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    message: Mapped[ChatMessage] = relationship(back_populates="sources")
