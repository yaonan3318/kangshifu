"""混合检索的筛选条件、命中片段和响应结构。"""

import uuid
from datetime import date

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    extension: str | None = Field(default=None, max_length=16)
    document_name: str | None = Field(default=None, max_length=200)
    created_from: date | None = None
    created_to: date | None = None
    limit: int = Field(default=10, ge=1, le=50)


class SearchResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    extension: str
    sequence_number: int
    content: str
    page_start: int | None
    page_end: int | None
    slide_number: int | None
    sheet_name: str | None
    row_start: int | None
    row_end: int | None
    section_path: list[str]
    ocr_confidence: float | None
    match_type: str


class SearchResponse(BaseModel):
    query: str
    items: list[SearchResult]
    total: int
