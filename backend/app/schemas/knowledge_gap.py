"""知识缺口中心的数据契约。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeGapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    reason: str
    count: int
    status: str
    assignee_user_id: uuid.UUID | None
    linked_document_ids: list[str] = Field(default_factory=list)
    note: str | None
    sample_message_id: uuid.UUID | None
    sample_answer: str | None
    latest_answer: str | None
    latest_confidence: str | None
    rerun_at: datetime | None
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


class KnowledgeGapListResponse(BaseModel):
    items: list[KnowledgeGapOut]
    page: int
    page_size: int
    total: int


class KnowledgeGapUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(OPEN|ASSIGNED|RESOLVED|IGNORED)$")
    assignee_user_id: uuid.UUID | None = None
    linked_document_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    note: str | None = Field(default=None, max_length=4000)


class KnowledgeGapStatsResponse(BaseModel):
    total: int
    open: int
    assigned: int
    resolved: int
    ignored: int
    by_status: dict = Field(default_factory=dict)
    by_reason: dict = Field(default_factory=dict)


class KnowledgeGapRerunResponse(BaseModel):
    gap_id: str
    question: str
    before: str | None = None
    after: str | None = None
    confidence: dict | None = None
    source_count: int = 0
