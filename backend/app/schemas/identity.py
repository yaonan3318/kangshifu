"""用户、部门与角色管理的数据契约。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RoleBrief(BaseModel):
    id: uuid.UUID
    name: str


class RoleOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime
    user_count: int = 0
    document_count: int = 0


class RoleListResponse(BaseModel):
    items: list[RoleOut]
    page: int
    page_size: int
    total: int


class DepartmentOut(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    enabled: bool
    created_at: datetime
    updated_at: datetime
    user_count: int = 0


class DepartmentTreeNode(DepartmentOut):
    children: list["DepartmentTreeNode"] = Field(default_factory=list)


DepartmentTreeNode.model_rebuild()


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    department_id: uuid.UUID | None
    department_name: str | None
    roles: list[RoleBrief] = Field(default_factory=list)
    is_super_admin: bool
    enabled: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    items: list[UserOut]
    page: int
    page_size: int
    total: int


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=2, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=255)
    department_id: uuid.UUID | None = None
    role_ids: list[uuid.UUID] = Field(default_factory=list)
    is_super_admin: bool = False
    enabled: bool = True


class UserUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    department_id: uuid.UUID | None = None
    role_ids: list[uuid.UUID] | None = None
    is_super_admin: bool | None = None
    enabled: bool | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=255)


class DepartmentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_id: uuid.UUID | None = None
    enabled: bool = True


class DepartmentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: uuid.UUID | None = None
    enabled: bool | None = None


class RoleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    enabled: bool = True


class RoleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None


class RoleUsersRequest(BaseModel):
    user_ids: list[uuid.UUID] = Field(default_factory=list)
