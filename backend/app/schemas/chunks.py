"""片段治理 API 数据结构。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    sequence_number: int
    content: str
    original_content: str | None
    enabled: bool
    manually_edited: bool
    token_count: int | None
    page_start: int | None
    page_end: int | None
    slide_number: int | None
    sheet_name: str | None
    section_path: list[str]
    ocr_confidence: float | None
    updated_at: datetime


class ChunkListResponse(BaseModel):
    items: list[ChunkResponse]
    page: int
    page_size: int
    total: int


class ChunkUpdateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)
