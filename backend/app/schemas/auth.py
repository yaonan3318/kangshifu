"""当前用户、登录状态与权限相关数据契约。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    department_id: uuid.UUID | None
    enabled: bool
    is_super_admin: bool
    last_login_at: datetime | None
    department_name: str | None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class AuthMeResponse(BaseModel):
    authenticated: bool
    user: UserOut | None = None
