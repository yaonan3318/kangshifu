"""P2-5 生成任务 ORM：把一次问答生成为可恢复、可取消的持久化 Answer Job。

生成任务不依赖浏览器连接存活：后台任务持续更新 ``current_stage`` 与 ``partial_content``，
页面刷新或切换后可按 ``event_cursor`` 续传，服务重启后未完成任务会被标记为失败。
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AnswerJobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RETRIEVING = "RETRIEVING"
    GENERATING = "GENERATING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES = {
    AnswerJobStatus.COMPLETED, AnswerJobStatus.FAILED, AnswerJobStatus.CANCELLED,
}


class AnswerJob(Base):
    __tablename__ = "answer_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assistant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assistants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 幂等请求 ID：同一 request_id 不会重复创建任务。
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True, index=True)
    status: Mapped[AnswerJobStatus] = mapped_column(
        Enum(AnswerJobStatus, native_enum=False), default=AnswerJobStatus.PENDING, index=True
    )
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    partial_content: Mapped[str] = mapped_column(Text, default="", server_default="")
    # 已产出的内容片段数；用于 SSE Last-Event-ID / 游标续传，避免重复内容。
    event_cursor: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="'{}'::jsonb")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
