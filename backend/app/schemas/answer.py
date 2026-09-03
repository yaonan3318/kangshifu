import uuid
from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ConversationTurn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(min_length=1, max_length=12_000)


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    use_deepseek: bool = False
    history: list[ConversationTurn] = Field(default_factory=list, max_length=6)
    extension: str | None = Field(default=None, max_length=16)
    document_name: str | None = Field(default=None, max_length=200)
    created_from: date | None = None
    created_to: date | None = None


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


class AnswerWarning(BaseModel):
    code: str
    message: str


class OllamaStatus(BaseModel):
    reachable: bool
    model: str
    installed: bool


class AnswerStatusResponse(BaseModel):
    ollama: OllamaStatus
    deepseek_configured: bool
    deepseek_model: str


class AnswerEvent(BaseModel):
    type: Literal["stage", "sources", "delta", "replace", "warning", "done", "error"]
    stage: str | None = None
    provider: AnswerProvider | None = None
    text: str | None = None
    sources: list[AnswerSource] | None = None
    warning: AnswerWarning | None = None
    scope: KnowledgeScope | None = None
    deepseek_requested: bool | None = None
    deepseek_used: bool | None = None
    source_count: int | None = None
    error: dict[str, Any] | None = None
