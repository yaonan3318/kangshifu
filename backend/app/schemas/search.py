"""混合检索的筛选条件、命中片段和响应结构。"""

import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.models.document import DocumentStatus


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    extension: str | None = Field(default=None, max_length=16)
    document_name: str | None = Field(default=None, max_length=200)
    created_from: date | None = None
    created_to: date | None = None
    knowledge_base_id: uuid.UUID | None = None
    # 助手知识库范围：允许检索的知识库白名单；为空表示不限制。
    knowledge_base_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=20)
    # 结构化元数据过滤；权限过滤始终先于这些条件执行。
    department_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    document_status: DocumentStatus | None = None
    relative_path: str | None = Field(default=None, max_length=2048)
    version_number: int | None = Field(default=None, ge=1)
    valid_only: bool = False
    include_stages: bool = False
    limit: int = Field(default=10, ge=1, le=50)


class SearchResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    extension: str
    document_version: int | None = None
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
    keyword_score: float | None = None
    vector_score: float | None = None
    fusion_score: float
    rerank_score: float | None = None
    final_score: float
    base_score: float | None = None
    feedback_boost: float = 0.0
    pre_rerank_rank: int | None = None
    post_rerank_rank: int | None = None


class QueryRewriteInfo(BaseModel):
    original: str
    standalone_question: str
    retrieval_query: str
    queries: list[str] = Field(default_factory=list)
    used_context: bool = False
    rewritten: bool = False
    warning: str | None = None


class RetrievalStageItem(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    sequence_number: int
    score: float
    content_preview: str


class SearchDiagnostics(BaseModel):
    normalized_query: str
    expanded_terms: list[str]
    mode: str
    warning: str | None = None
    no_answer_reason: str | None = None
    timings_ms: dict[str, float] = Field(default_factory=dict)
    stages: dict[str, list[RetrievalStageItem]] = Field(default_factory=dict)
    queries: list[str] = Field(default_factory=list)
    retrieval_query: str | None = None
    rerank_applied: bool = False
    candidate_count: int = 0


class SearchResponse(BaseModel):
    query: str
    items: list[SearchResult]
    total: int
    diagnostics: SearchDiagnostics
