"""助手配置的数据契约。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AssistantOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    avatar: str
    welcome_message: str | None
    system_prompt: str | None
    model_provider: str
    model_name: str | None
    use_deepseek_allowed: bool
    default_deepseek_enabled: bool
    deepseek_enabled: bool
    harness_enabled: bool
    harness_context: str | None
    harness_namespace: str
    retrieval_limit: int
    temperature: float
    recommended_questions: list[str] = Field(default_factory=list)
    enabled: bool
    created_at: datetime
    updated_at: datetime
    knowledge_base_ids: list[uuid.UUID] = Field(default_factory=list)


class AssistantUpsert(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    avatar: str | None = Field(default=None, min_length=1, max_length=16)
    welcome_message: str | None = Field(default=None, max_length=2000)
    system_prompt: str | None = Field(default=None, max_length=8000)
    model_provider: str | None = Field(default=None, pattern="^(ollama|deepseek)$")
    model_name: str | None = Field(default=None, max_length=255)
    use_deepseek_allowed: bool | None = None
    default_deepseek_enabled: bool | None = None
    deepseek_enabled: bool | None = None
    harness_enabled: bool | None = None
    harness_context: str | None = Field(default=None, max_length=255)
    harness_namespace: str | None = Field(default=None, min_length=1, max_length=255)
    retrieval_limit: int | None = Field(default=None, ge=1, le=20)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    recommended_questions: list[str] | None = Field(default=None, max_length=20)
    enabled: bool | None = None


class AssistantKnowledgeBasesPut(BaseModel):
    knowledge_base_ids: list[uuid.UUID] = Field(default_factory=list)


class AssistantListResponse(BaseModel):
    items: list[AssistantOut]
    total: int
