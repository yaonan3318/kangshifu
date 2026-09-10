"""Chatflow 流程定义、版本与调试运行的数据契约。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    graph: dict | None = None


class ChatflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    graph: dict | None = None
    enabled: bool | None = None


class ChatflowVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chatflow_id: uuid.UUID
    version: int
    graph: dict
    note: str | None
    created_at: datetime


class ChatflowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    draft_graph: dict
    published_graph: dict
    published_version: int
    enabled: bool
    bound_assistant_count: int = 0
    created_at: datetime
    updated_at: datetime


class ChatflowListResponse(BaseModel):
    items: list[ChatflowOut]
    total: int


class ChatflowPublishRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ChatflowRollbackRequest(BaseModel):
    version: int = Field(ge=1)


class ChatflowDebugRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    knowledge_base_id: uuid.UUID | None = None
    include_generation: bool = False


class ChatflowDebugResponse(BaseModel):
    nodes: list[dict]
    total_ms: float
    final: dict | None = None


class NodeTypeOut(BaseModel):
    type: str
    label: str
    category: str
    config_fields: list[dict] = Field(default_factory=list)


class NodeTypeListResponse(BaseModel):
    items: list[NodeTypeOut]
    total: int
