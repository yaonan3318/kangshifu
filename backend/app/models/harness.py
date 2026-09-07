"""Harness 持久化模型：任务、工具步骤和写操作审批。"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class HarnessTaskStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class HarnessStepStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ApprovalStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    EXECUTED = "EXECUTED"


class HarnessTask(Base):
    __tablename__ = "harness_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(String(255))
    namespace: Mapped[str] = mapped_column(String(255), default="default")
    status: Mapped[HarnessTaskStatus] = mapped_column(Enum(HarnessTaskStatus, native_enum=False), index=True)
    model: Mapped[str] = mapped_column(String(255))
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    max_steps: Mapped[int] = mapped_column(Integer, default=8)
    history: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    deployment_yaml: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    steps: Mapped[list["HarnessStep"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    approvals: Mapped[list["HarnessApproval"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class HarnessStep(Base):
    __tablename__ = "harness_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("harness_tasks.id", ondelete="CASCADE"), index=True)
    sequence_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[HarnessStepStatus] = mapped_column(Enum(HarnessStepStatus, native_enum=False))
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[HarnessTask] = relationship(back_populates="steps")


class HarnessApproval(Base):
    __tablename__ = "harness_approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("harness_tasks.id", ondelete="CASCADE"), index=True)
    step_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("harness_steps.id", ondelete="CASCADE"))
    status: Mapped[ApprovalStatus] = mapped_column(Enum(ApprovalStatus, native_enum=False), index=True)
    tool_name: Mapped[str] = mapped_column(String(128))
    context: Mapped[str] = mapped_column(String(255))
    namespace: Mapped[str] = mapped_column(String(255))
    target: Mapped[str] = mapped_column(String(512))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB)
    yaml_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    yaml_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dry_run_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    diff_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_versions: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[HarnessTask] = relationship(back_populates="approvals")
