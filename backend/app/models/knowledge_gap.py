"""知识缺口 ORM：自动沉淀未答/低置信/负反馈/高频无资料等问题，供管理员闭环处理。"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KnowledgeGapReason(str, enum.Enum):
    NO_ANSWER = "NO_ANSWER"                 # 未找到答案
    LOW_CONFIDENCE = "LOW_CONFIDENCE"       # 低置信度
    NEGATIVE_FEEDBACK = "NEGATIVE_FEEDBACK" # 用户评价“没帮助”
    WRONG_DOCUMENT = "WRONG_DOCUMENT"       # 召回错误文档 / 引用不正确
    PERMISSION_RESTRICTED = "PERMISSION_RESTRICTED"  # 有资料但无权访问


class KnowledgeGapStatus(str, enum.Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    RESOLVED = "RESOLVED"
    IGNORED = "IGNORED"


class KnowledgeGap(Base):
    __tablename__ = "knowledge_gaps"
    __table_args__ = (
        UniqueConstraint("normalized_question", "reason", name="uq_knowledge_gaps_question_reason"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_question: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    reason: Mapped[KnowledgeGapReason] = mapped_column(Enum(KnowledgeGapReason, native_enum=False), index=True)
    count: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    status: Mapped[KnowledgeGapStatus] = mapped_column(
        Enum(KnowledgeGapStatus, native_enum=False), default=KnowledgeGapStatus.OPEN, index=True,
    )
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    linked_document_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    note: Mapped[str | None] = mapped_column(Text)
    sample_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    sample_answer: Mapped[str | None] = mapped_column(Text)
    latest_answer: Mapped[str | None] = mapped_column(Text)
    latest_confidence: Mapped[str | None] = mapped_column(String(16))
    rerun_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
