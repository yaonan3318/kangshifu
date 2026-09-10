"""答案反馈 ORM：点赞/点踩、原因与处理闭环。"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class FeedbackRating(str, enum.Enum):
    UP = "UP"
    DOWN = "DOWN"


class AnswerFeedback(Base):
    __tablename__ = "answer_feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    # 反馈可归因到被引用文档，供“反馈影响检索排序”统计使用；无引用时为 NULL。
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    rating: Mapped[FeedbackRating] = mapped_column(Enum(FeedbackRating, native_enum=False))
    reasons: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    resolution_note: Mapped[str | None] = mapped_column(Text)

    message = relationship("ChatMessage", foreign_keys=[message_id])


class AnswerFeedbackDocument(Base):
    """一次反馈关联的引用文档；同一回答同一文档只保留一条，供排序统计使用。"""
    __tablename__ = "answer_feedback_documents"
    __table_args__ = (
        UniqueConstraint("feedback_id", "document_id", name="uq_answer_feedback_documents"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    feedback_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("answer_feedback.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    citation_number: Mapped[int | None] = mapped_column(Integer, nullable=True)


class DocumentFeedbackStats(Base):
    """按文档聚合的反馈统计；排序只在其样本达到门槛后才产生小幅调整。"""
    __tablename__ = "document_feedback_stats"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    up_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    down_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    sample_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    score: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
