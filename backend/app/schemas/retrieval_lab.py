"""检索实验室：诊断、评测集、标准问题、配置版本与运行对比结构。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.search import QueryRewriteInfo, SearchDiagnostics, SearchResult


class RetrievalInspectRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    knowledge_base_id: uuid.UUID | None = None
    limit: int = Field(default=10, ge=1, le=50)
    # 可选：传入最近对话以演示多轮上下文补全。
    history: list[dict] = Field(default_factory=list, max_length=6)


class RetrievalInspectResponse(BaseModel):
    items: list[SearchResult]
    diagnostics: SearchDiagnostics
    query_rewrite: QueryRewriteInfo | None = None
    queries: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- 检索词典

class DictionaryEntryCreate(BaseModel):
    category: str = Field(pattern="^(SYNONYM|ABBREVIATION|PROPER_NOUN|CROSS_LANGUAGE)$")
    term: str = Field(min_length=1, max_length=255)
    expansions: list[str] = Field(default_factory=list, max_length=50)
    enabled: bool = True


class DictionaryEntryUpdate(BaseModel):
    term: str | None = Field(default=None, min_length=1, max_length=255)
    expansions: list[str] | None = Field(default=None, max_length=50)
    enabled: bool | None = None


class DictionaryEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    term: str
    expansions: list[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class DictionaryListResponse(BaseModel):
    items: list[DictionaryEntryResponse]
    total: int


# ---------------------------------------------------------------- 评测集

class EvaluationSetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    knowledge_base_id: uuid.UUID | None = None
    enabled: bool = True


class EvaluationSetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    knowledge_base_id: uuid.UUID | None = None
    enabled: bool | None = None


class EvaluationSetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    knowledge_base_id: uuid.UUID | None
    enabled: bool
    case_count: int = 0
    created_at: datetime
    updated_at: datetime


class EvaluationSetListResponse(BaseModel):
    items: list[EvaluationSetResponse]
    total: int


# ---------------------------------------------------------------- 标准问题

class TestCaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    question: str = Field(min_length=1, max_length=1000)
    knowledge_base_id: uuid.UUID | None = None
    expected_document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    expected_chunk_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    must_cite_document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    forbidden_document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    expected_keywords: list[str] = Field(default_factory=list, max_length=30)
    expected_answer_keypoints: list[str] = Field(default_factory=list, max_length=30)
    expected_no_answer: bool = False
    enabled: bool = True


class TestCaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    question: str | None = Field(default=None, min_length=1, max_length=1000)
    knowledge_base_id: uuid.UUID | None = None
    expected_document_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    expected_chunk_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    must_cite_document_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    forbidden_document_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    expected_keywords: list[str] | None = Field(default=None, max_length=30)
    expected_answer_keypoints: list[str] | None = Field(default=None, max_length=30)
    expected_no_answer: bool | None = None
    enabled: bool | None = None


class TestCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    evaluation_set_id: uuid.UUID | None
    name: str
    question: str
    knowledge_base_id: uuid.UUID | None
    expected_document_ids: list[str]
    expected_chunk_ids: list[str] = Field(default_factory=list)
    must_cite_document_ids: list[str]
    forbidden_document_ids: list[str]
    expected_keywords: list[str]
    expected_answer_keypoints: list[str]
    expected_no_answer: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime


class TestCaseListResponse(BaseModel):
    items: list[TestCaseResponse]
    total: int


class CaseImportResult(BaseModel):
    created: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- 配置版本

class ConfigVersionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    config: dict = Field(default_factory=dict)
    is_default: bool = False


class ConfigVersionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    config: dict | None = None
    is_default: bool | None = None


class ConfigVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    config: dict
    is_default: bool
    created_at: datetime
    updated_at: datetime


class ConfigVersionListResponse(BaseModel):
    items: list[ConfigVersionResponse]
    total: int


# ---------------------------------------------------------------- 运行与对比

class RunCreate(BaseModel):
    evaluation_set_id: uuid.UUID
    config_version_id: uuid.UUID | None = None
    limit: int = Field(default=5, ge=1, le=20)
    include_answers: bool = False


class TestRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    evaluation_set_id: uuid.UUID | None
    config_version_id: uuid.UUID | None
    settings_snapshot: dict
    config_snapshot: dict
    results: list[dict]
    metrics: dict
    created_at: datetime


class TestRunListResponse(BaseModel):
    items: list[TestRunResponse]
    total: int


class RunCompareResponse(BaseModel):
    left: TestRunResponse
    right: TestRunResponse
    metric_deltas: dict
    metric_changes: list[dict] = Field(default_factory=list)
    config_differences: list[dict]
    case_changes: list[dict]
