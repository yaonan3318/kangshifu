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
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)
