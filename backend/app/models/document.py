"""文档元数据 ORM 模型；原文件在磁盘，数据库保存路径、状态和索引信息。"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.identity import DocumentVisibility


class DocumentStatus(str, enum.Enum):
    """文档从上传到可检索的状态机，以及解析/OCR/索引失败状态。"""
    PENDING = "PENDING"
    PARSING = "PARSING"
    CHUNKING = "CHUNKING"
    PARSED = "PARSED"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    READY = "READY"
    INDEX_FAILED = "INDEX_FAILED"
    PARSE_FAILED = "PARSE_FAILED"
    OCR_FAILED = "OCR_FAILED"
    DELETING = "DELETING"


class Document(Base):
    """一份受管文档；与文本片段和后台任务是一对多关系。"""
    __tablename__ = "documents"
    __table_args__ = (CheckConstraint("size_bytes >= 0", name="ck_documents_size_nonnegative"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_name: Mapped[str] = mapped_column(String(1024))
    stored_path: Mapped[str] = mapped_column(String(2048))
    relative_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    extension: Mapped[str] = mapped_column(String(16), index=True)
    mime_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus, native_enum=False), index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="RESTRICT"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    deleted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[DocumentVisibility] = mapped_column(
        Enum(DocumentVisibility, native_enum=False), default=DocumentVisibility.COMPANY, index=True
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    jobs: Mapped[list["ProcessingJob"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    batch_files: Mapped[list["BatchFile"]] = relationship(back_populates="document")
    knowledge_base: Mapped["KnowledgeBase"] = relationship(back_populates="documents")
    tags: Mapped[list["Tag"]] = relationship(secondary="document_tags", back_populates="documents")
    previous_version: Mapped["Document | None"] = relationship(remote_side="Document.id", foreign_keys=[previous_version_id])


from app.models.processing_job import ProcessingJob  # noqa: E402
from app.models.document_chunk import DocumentChunk  # noqa: E402
from app.models.upload_batch import BatchFile  # noqa: E402
from app.models.knowledge_base import KnowledgeBase  # noqa: E402
from app.models.tag import Tag  # noqa: E402
