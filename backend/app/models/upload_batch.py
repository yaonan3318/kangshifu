"""批量导入 ORM：批次负责组织文件，Document 继续作为去重后的物理与解析对象。"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class BatchStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    UPLOADING = "UPLOADING"
    PROCESSING = "PROCESSING"
    PARTIAL_FAILED = "PARTIAL_FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BatchUploadStatus(str, enum.Enum):
    PENDING = "PENDING"
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    DUPLICATE = "DUPLICATE"
    FAILED = "FAILED"


class BatchProcessingStatus(str, enum.Enum):
    WAITING = "WAITING"
    PROCESSING = "PROCESSING"
    PARSED = "PARSED"
    INDEXED = "INDEXED"
    FAILED = "FAILED"
    IGNORED = "IGNORED"


class UploadBatch(Base):
    __tablename__ = "upload_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(128))
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[BatchStatus] = mapped_column(Enum(BatchStatus, native_enum=False), index=True, default=BatchStatus.DRAFT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    files: Mapped[list["BatchFile"]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class BatchFile(Base):
    __tablename__ = "batch_files"
    __table_args__ = (UniqueConstraint("batch_id", "relative_path", name="uq_batch_files_path"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("upload_batches.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    relative_path: Mapped[str] = mapped_column(String(2048))
    original_name: Mapped[str] = mapped_column(String(1024))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    upload_status: Mapped[BatchUploadStatus] = mapped_column(Enum(BatchUploadStatus, native_enum=False), index=True, default=BatchUploadStatus.PENDING)
    processing_status: Mapped[BatchProcessingStatus] = mapped_column(Enum(BatchProcessingStatus, native_enum=False), index=True, default=BatchProcessingStatus.WAITING)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_stage: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    batch: Mapped[UploadBatch] = relationship(back_populates="files")
    document: Mapped["Document | None"] = relationship(back_populates="batch_files")


from app.models.document import Document  # noqa: E402
