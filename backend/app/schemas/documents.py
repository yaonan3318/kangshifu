"""文档 API 的 Pydantic 请求/响应结构，隔离 HTTP 数据与 ORM 对象。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import DocumentStatus


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_name: str
    extension: str
    mime_type: str
    size_bytes: int
    sha256: str
    status: DocumentStatus
    error_code: str | None
    error_message: str | None
    parser_name: str | None
    parser_version: str | None
    created_at: datetime
    updated_at: datetime
    knowledge_base_id: uuid.UUID
    relative_path: str | None
    version_number: int
    previous_version_id: uuid.UUID | None
    superseded_by_id: uuid.UUID | None = None
    enabled: bool
    visibility: str
    owner_user_id: uuid.UUID | None
    author: str | None = None
    department_id: uuid.UUID | None = None
    topic: str | None = None
    related_document_ids: list[str] = Field(default_factory=list)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    sensitivity_level: str = "INTERNAL"
    external_llm_allowed: bool = True
    deleted_at: datetime | None
    deleted_reason: str | None
    metadata_json: dict
    tags: list[str] = Field(default_factory=list)
    chunk_count: int = 0


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    page: int
    page_size: int
    total: int


class DocumentChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence_number: int
    page_start: int | None
    page_end: int | None
    slide_number: int | None
    sheet_name: str | None
    row_start: int | None
    row_end: int | None
    section_path: list[str]
    content: str
    ocr_confidence: float | None
    chunk_role: str = "normal"
    parent_chunk_id: uuid.UUID | None = None


class DocumentContentResponse(BaseModel):
    items: list[DocumentChunkResponse]
    page: int
    page_size: int
    total: int


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class DocumentFilters(BaseModel):
    query: str | None = Field(default=None, max_length=200)
    extension: str | None = Field(default=None, max_length=16)
    status: DocumentStatus | None = None
    knowledge_base_id: uuid.UUID | None = None
    tag: str | None = Field(default=None, max_length=128)
    include_deleted: bool = False
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)


class DocumentUpdateRequest(BaseModel):
    knowledge_base_id: uuid.UUID | None = None
    relative_path: str | None = Field(default=None, max_length=2048)
    metadata: dict | None = None
    tags: list[str] | None = Field(default=None, max_length=30)
    # P2-6 文档理解元数据：作者/部门/主题/关联文档/有效期。
    author: str | None = Field(default=None, max_length=255)
    department_id: uuid.UUID | None = None
    topic: str | None = Field(default=None, max_length=255)
    related_document_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class ChunkPreviewRequest(BaseModel):
    """切片预览：可临时覆盖知识库的切片配置，不写入数据库。"""
    chunking_config: dict | None = None
    limit: int = Field(default=50, ge=1, le=200)


class ChunkPreviewItem(BaseModel):
    sequence_number: int
    content: str
    length: int
    page_start: int | None
    page_end: int | None
    slide_number: int | None
    sheet_name: str | None
    row_start: int | None
    row_end: int | None
    section_path: list[str]
    block_type: str
    chunk_role: str


class ChunkPreviewResponse(BaseModel):
    items: list[ChunkPreviewItem]
    total: int
    config: dict


class DocumentDeleteRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class DocumentExternalPolicyRequest(BaseModel):
    sensitivity_level: str = Field(pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$")
    external_llm_allowed: bool
