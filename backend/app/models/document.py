"""文档元数据 ORM 模型；原文件在磁盘，数据库保存路径、状态和索引信息。"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Enum, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    jobs: Mapped[list["ProcessingJob"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


from app.models.processing_job import ProcessingJob  # noqa: E402
from app.models.document_chunk import DocumentChunk  # noqa: E402
