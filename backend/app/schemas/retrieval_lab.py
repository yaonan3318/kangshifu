"""检索实验室标准问题、运行和明细结构。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.search import SearchDiagnostics, SearchResult


class RetrievalInspectRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    knowledge_base_id: uuid.UUID | None = None
    limit: int = Field(default=10, ge=1, le=50)


class RetrievalInspectResponse(BaseModel):
    items: list[SearchResult]
    diagnostics: SearchDiagnostics


class TestCaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    question: str = Field(min_length=1, max_length=1000)
    knowledge_base_id: uuid.UUID | None = None
    expected_document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    expected_keywords: list[str] = Field(default_factory=list, max_length=30)
    expected_no_answer: bool = False
    enabled: bool = True


class TestCaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    question: str | None = Field(default=None, min_length=1, max_length=1000)
    knowledge_base_id: uuid.UUID | None = None
    expected_document_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    expected_keywords: list[str] | None = Field(default=None, max_length=30)
    expected_no_answer: bool | None = None
    enabled: bool | None = None


class TestCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    question: str
    knowledge_base_id: uuid.UUID | None
    expected_document_ids: list[str]
    expected_keywords: list[str]
    expected_no_answer: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime


class TestCaseListResponse(BaseModel):
    items: list[TestCaseResponse]
    total: int


class TestRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    settings_snapshot: dict
    results: list[dict]
    metrics: dict
    created_at: datetime


class TestRunListResponse(BaseModel):
    items: list[TestRunResponse]
    total: int
