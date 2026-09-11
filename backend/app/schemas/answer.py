"""RAG 问答请求、运行状态、引用来源和 SSE 事件的数据契约。"""

import uuid

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.document import DocumentStatus
from app.schemas.search import QueryRewriteInfo


class ConversationTurn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(min_length=1, max_length=12_000)


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    session_id: uuid.UUID | None = None
    assistant_id: uuid.UUID | None = None
    regenerate_message_id: uuid.UUID | None = None
    knowledge_base_id: uuid.UUID | None = None
    use_deepseek: bool = False
    use_harness: bool = False
    k8s_context: str | None = Field(default=None, max_length=255)
    k8s_namespace: str | None = Field(default=None, max_length=255)
    deployment_yaml: str | None = Field(default=None, max_length=1_048_576)
    history: list[ConversationTurn] = Field(default_factory=list, max_length=6)
    extension: str | None = Field(default=None, max_length=16)
    document_name: str | None = Field(default=None, max_length=200)
    created_from: date | None = None
    created_to: date | None = None
    # P2-1 结构化元数据过滤；权限过滤始终先于这些条件执行。
    tags: list[str] = Field(default_factory=list, max_length=20)
    department_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    document_status: DocumentStatus | None = None
    relative_path: str | None = Field(default=None, max_length=2048)
    version_number: int | None = Field(default=None, ge=1)
    valid_only: bool = False
    # P2-1 检索增强开关；为空时使用检索配置版本中的设置。
    use_query_rewrite: bool | None = None
    use_multi_query: bool | None = None
    # P2-5：幂等请求 ID；同一 request_id 不会重复创建生成任务。
    request_id: str | None = Field(default=None, max_length=128)


class KnowledgeScope(str, Enum):
    INTERNAL = "INTERNAL"
    INTERNAL_LIMITED = "INTERNAL_LIMITED"
    GENERAL = "GENERAL"
    NONE = "NONE"


class AnswerProvider(str, Enum):
    LOCAL = "LOCAL"
    DEEPSEEK = "DEEPSEEK"


class AnswerSource(BaseModel):
    citation_number: int
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
    score: float | None = None
    # 检索日志：召回（RRF 融合后、精排前）排名与精排后排名，用于追溯排序变化。
    retrieval_rank: int | None = None
    pre_rerank_rank: int | None = None
    post_rerank_rank: int | None = None


class AnswerWarning(BaseModel):
    code: str
    message: str


class AnswerJobOut(BaseModel):
    """P2-5 生成任务状态；页面刷新/断线后可据此恢复。"""

    id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    status: str
    current_stage: str | None = None
    partial_content: str = ""
    event_cursor: int = 0
    metrics: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None


class OllamaStatus(BaseModel):
    reachable: bool
    model: str
    installed: bool


class AnswerStatusResponse(BaseModel):
    ollama: OllamaStatus
    deepseek_configured: bool
    deepseek_model: str


class AnswerEvent(BaseModel):
    type: Literal[
        "stage", "sources", "delta", "replace", "warning", "metrics", "done", "error",
        "query_rewrite", "confidence", "citation_check", "no_answer", "suggestions",
        "harness_started", "tool_requested", "tool_running", "tool_result",
        "approval_required", "approval_result", "harness_done",
    ]
    stage: str | None = None
    detail: dict[str, Any] | None = None
    suggestions: list[str] | None = None
    provider: AnswerProvider | None = None
    text: str | None = None
    sources: list[AnswerSource] | None = None
    query_rewrite: QueryRewriteInfo | None = None
    confidence: dict[str, Any] | None = None
    citation_check: dict[str, Any] | None = None
    no_answer: dict[str, Any] | None = None
    question_type: str | None = None
    warning: AnswerWarning | None = None
    metrics: dict[str, Any] | None = None
    scope: KnowledgeScope | None = None
    deepseek_requested: bool | None = None
    deepseek_used: bool | None = None
    source_count: int | None = None
    error: dict[str, Any] | None = None
    task_id: uuid.UUID | None = None
    step: int | None = None
    tool: str | None = None
    tool_arguments: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
