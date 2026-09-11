"""反馈治理 ORM：点赞/点踩/举报、上下文快照、处理队列、复验与聚合。

P2-7A 在原有 ``answer_feedback`` 基础上做增量扩展：
- 同一用户对同一条回答只保留一条当前有效反馈（数据库唯一约束 + 后端覆盖）；
- 反馈发生时冻结回答/引用/检索配置等上下文，回答或文档后来变化也不丢历史；
- 负反馈进入管理员处理队列，状态流转由后端枚举校验；
- 每次变更保留历史记录，供审计追溯。

P2-7B/C 的聚合与复验表也集中在本模块，方便 Alembic 统一加载。
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class FeedbackRating(str, enum.Enum):
    """兼容既有排序统计的极性；REPORT 与 DOWN 同属负向。"""

    UP = "UP"
    DOWN = "DOWN"
    REPORT = "REPORT"


class FeedbackType(str, enum.Enum):
    UP = "UP"
    DOWN = "DOWN"
    REPORT = "REPORT"


class FeedbackCaseStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    WAIT_VERIFY = "WAIT_VERIFY"
    RESOLVED = "RESOLVED"
    IGNORED = "IGNORED"


class FeedbackPriority(str, enum.Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class VerificationStatus(str, enum.Enum):
    NOT_RUN = "NOT_RUN"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"


class AnswerFeedback(Base):
    __tablename__ = "answer_feedback"
    __table_args__ = (
        # 同一用户对同一条回答只允许一条当前有效反馈；user_id 为空的历史匿名数据不受影响。
        UniqueConstraint("user_id", "message_id", name="uq_answer_feedback_user_message"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    # 反馈可归因到被引用文档，供“反馈影响检索排序”统计使用；无引用时为 NULL。
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    rating: Mapped[FeedbackRating] = mapped_column(Enum(FeedbackRating, native_enum=False), index=True)
    feedback_type: Mapped[FeedbackType] = mapped_column(
        Enum(FeedbackType, native_enum=False), default=FeedbackType.UP, index=True
    )
    reasons: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    comment: Mapped[str | None] = mapped_column(Text)

    # ---------------------------------------------------------- 上下文快照
    chat_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assistant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    question_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    knowledge_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    chunk_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    document_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    document_versions: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    knowledge_base_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    retrieval_config_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("retrieval_config_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    answer_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    answer_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 问题指纹：按“知识库 + 片段 + 问题簇”聚合反馈时使用，简单可解释。
    query_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
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
    """按文档聚合的反馈统计（兼容旧排序统计）；新排序使用 feedback_aggregates。"""
    __tablename__ = "document_feedback_stats"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    up_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    down_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    sample_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    score: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FeedbackHistory(Base):
    """反馈字段变更历史；仅追加，不修改，用于审计追溯。"""

    __tablename__ = "feedback_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    feedback_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("answer_feedback.id", ondelete="CASCADE"), index=True
    )
    change_type: Mapped[str] = mapped_column(String(32))
    previous_rating: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_rating: Mapped[str | None] = mapped_column(String(16), nullable=True)
    previous_reasons: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    new_reasons: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    previous_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class FeedbackRetrievalSnapshot(Base):
    """反馈发生时的检索上下文快照：每个引用片段的分数、排名与所属知识库。"""

    __tablename__ = "feedback_retrieval_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    feedback_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("answer_feedback.id", ondelete="CASCADE"), index=True
    )
    retrieval_config_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("retrieval_config_versions.id", ondelete="SET NULL"), nullable=True
    )
    # 列表元素：{chunk_id, document_id, knowledge_base_id, score, retrieval_rank}
    chunks: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeedbackCase(Base):
    """负反馈处理工单；每个负反馈最多一个工单。"""

    __tablename__ = "feedback_cases"
    __table_args__ = (
        UniqueConstraint("feedback_id", name="uq_feedback_cases_feedback_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    feedback_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("answer_feedback.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[FeedbackCaseStatus] = mapped_column(
        Enum(FeedbackCaseStatus, native_enum=False), default=FeedbackCaseStatus.PENDING, index=True
    )
    priority: Mapped[FeedbackPriority] = mapped_column(
        Enum(FeedbackPriority, native_enum=False), default=FeedbackPriority.NORMAL, index=True
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    fix_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    fix_config_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("retrieval_config_versions.id", ondelete="SET NULL"), nullable=True
    )
    last_verification_result: Mapped[VerificationStatus | None] = mapped_column(
        Enum(VerificationStatus, native_enum=False), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FeedbackCaseEvent(Base):
    """工单状态流转/分配/复验事件流水。"""

    __tablename__ = "feedback_case_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feedback_cases.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class FeedbackAggregate(Base):
    """按 (知识库, 片段, 问题指纹) 聚合的反馈样本；排序微调只读取本表。"""

    __tablename__ = "feedback_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_base_id", "chunk_id", "query_fingerprint",
            name="uq_feedback_aggregates_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="CASCADE"), index=True
    )
    query_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    positive_users: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    negative_users: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    effective_users: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    admin_verified_positive: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    admin_verified_negative: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    raw_feedback: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    bounded_feedback: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    feedback_boost: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FeedbackVerificationRun(Base):
    """历史负反馈复验：保存新旧回答/引用/配置对比，不覆盖原始回答快照。"""

    __tablename__ = "feedback_verification_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feedback_cases.id", ondelete="CASCADE"), index=True
    )
    feedback_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("answer_feedback.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, native_enum=False), default=VerificationStatus.NOT_RUN, index=True
    )
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_sources: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    before_config_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    after_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_sources: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    after_config_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    after_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    base_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_answer: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    admin_conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
