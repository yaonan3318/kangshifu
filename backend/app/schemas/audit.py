"""审计日志响应契约。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    username: str | None
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    detail: dict
    ip_address: str | None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogOut]
    page: int
    page_size: int
    total: int
