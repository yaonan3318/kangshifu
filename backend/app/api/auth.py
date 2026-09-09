"""登录、登出、当前用户与会话接口；用户管理接口也放在同一模块。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.db import get_session
from app.errors import AppError
from app.models import Department, Role, User
from app.schemas.auth import AuthMeResponse, LoginRequest, UserOut
from app.services.auth import (
    LoginRateLimiter, authenticate, create_session_token, find_by_token,
    hash_password, revoke_session,
)
from app.services.permissions import require_admin, require_user

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = LoginRateLimiter()

COOKIE = "cs_session"


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id, username=user.username, display_name=user.display_name,
        department_id=user.department_id, enabled=user.enabled,
        is_super_admin=user.is_super_admin, last_login_at=user.last_login_at,
        department_name=user.department.name if user.department else None,
        roles=[role.name for role in user.roles],
    )


def current_user(request: Request) -> User | None:
    """从中间件解析结果返回当前用户；未登录返回 None。"""
    return getattr(request.state, "auth_user", None)


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """校验用户名密码并写入 HttpOnly 会话 Cookie。"""
    limiter.limit = settings.auth_login_rate_limit
    limiter.window = settings.auth_login_rate_window_seconds
    limiter.check(request.client.host if request.client else None)
    user = authenticate(session, body.username, body.password)
    token = create_session_token(session, user, request.client.host if request.client else None, days=settings.auth_session_days)
    response.set_cookie(
        COOKIE, token, max_age=settings.auth_session_days * 86400,
        httponly=True, samesite="lax", path="/",
    )
    return {"authenticated": True, "user": _user_out(user)}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
):
    token = request.cookies.get(COOKIE)
    revoke_session(session, token or "")
    response.delete_cookie(COOKIE, path="/")
    return {"authenticated": False}


@router.get("/me")
async def me(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AuthMeResponse:
    """返回当前登录状态；未登录时 authenticated=false。"""
    token = request.cookies.get(COOKIE)
    user = None
    if token:
        auth_session = find_by_token(session, token)
        if auth_session:
            user = session.scalar(
                select(User).where(User.id == auth_session.user_id)
                .options(selectinload(User.roles), selectinload(User.department))
            )
    if user is None or not user.enabled:
        return AuthMeResponse(authenticated=False)
    return AuthMeResponse(authenticated=True, user=_user_out(user))


# ---------- 管理员用户管理 ----------
USER_PREFIX = "/api/users"
user_router = APIRouter(prefix=USER_PREFIX, tags=["users"])


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=6, max_length=255)
    department_id: uuid.UUID | None = None
    role_ids: list[uuid.UUID] = Field(default_factory=list)
    is_super_admin: bool = False
    enabled: bool = True


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=6, max_length=255)
    department_id: uuid.UUID | None = None
    role_ids: list[uuid.UUID] | None = None
    is_super_admin: bool | None = None
    enabled: bool | None = None


def _load_user(session: Session, user_id: uuid.UUID) -> User:
    user = session.scalar(select(User).where(User.id == user_id).options(selectinload(User.roles), selectinload(User.department)))
    if user is None:
        raise AppError("USER_NOT_FOUND", "用户不存在", 404)
    return user


@user_router.get("")
async def list_users(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    search: str | None = None,
) -> dict:
    require_admin(current_user(request))
    statement = select(User).options(selectinload(User.roles), selectinload(User.department))
    if search:
        statement = statement.where(User.username.ilike(f"%{search}%") | User.display_name.ilike(f"%{search}%"))
    rows = session.scalars(statement.order_by(User.created_at.desc())).all()
    return {"items": [_user_out(item) for item in rows], "total": len(rows)}


@user_router.post("", status_code=201)
async def create_user(
    body: UserCreate,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> UserOut:
    require_admin(current_user(request))
    if session.scalar(select(User).where(User.username == body.username.strip())):
        raise AppError("USERNAME_EXISTS", "用户名已存在", 409)
    if body.department_id is not None and session.get(Department, body.department_id) is None:
        raise AppError("DEPARTMENT_NOT_FOUND", "部门不存在", 404)
    roles = []
    if body.role_ids:
        roles = list(session.scalars(select(Role).where(Role.id.in_(body.role_ids))).all())
    user = User(
        username=body.username.strip(), display_name=body.display_name.strip(),
        password_hash=hash_password(body.password), department_id=body.department_id,
        enabled=body.enabled, is_super_admin=body.is_super_admin,
    )
    user.roles.extend(roles)
    session.add(user)
    session.commit()
    return _user_out(_load_user(session, user.id))


@user_router.patch("/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    body: UserPatch,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> UserOut:
    current = require_admin(current_user(request))
    target = _load_user(session, user_id)
    if body.display_name is not None:
        target.display_name = body.display_name.strip()
    if body.password is not None:
        target.password_hash = hash_password(body.password)
    if body.department_id is not None:
        if session.get(Department, body.department_id) is None:
            raise AppError("DEPARTMENT_NOT_FOUND", "部门不存在", 404)
        target.department_id = body.department_id
    elif "department_id" in body.model_fields_set and body.department_id is None:
        target.department_id = None
    if body.is_super_admin is not None and target.id != current.id:
        target.is_super_admin = body.is_super_admin
    if body.enabled is not None:
        target.enabled = body.enabled
    if body.role_ids is not None:
        target.roles = list(session.scalars(select(Role).where(Role.id.in_(body.role_ids))).all())
    session.commit()
    return _user_out(_load_user(session, user_id))


@router.get("/departments", tags=["auth"])
async def list_departments(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    require_user(current_user(request))
    rows = session.scalars(select(Department).order_by(Department.name)).all()
    return {"items": [{"id": item.id, "name": item.name, "parent_id": item.parent_id, "enabled": item.enabled} for item in rows], "total": len(rows)}


@router.get("/roles", tags=["auth"])
async def list_roles(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    require_user(current_user(request))
    rows = session.scalars(select(Role).order_by(Role.name)).all()
    return {"items": [{"id": item.id, "name": item.name, "description": item.description} for item in rows], "total": len(rows)}
