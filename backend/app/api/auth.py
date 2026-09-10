"""登录、登出、当前用户与会话接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.db import get_session
from app.errors import AppError
from app.models import Department, Role, User
from app.schemas.auth import AuthMeResponse, LoginRequest, UserOut
from app.services.auth import (
    LoginRateLimiter, authenticate, create_session_token, find_by_token, revoke_session,
)
from app.services.permissions import require_user
from app.services.rbac import effective_permissions

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = LoginRateLimiter()

COOKIE = "cs_session"


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id, username=user.username, display_name=user.display_name,
        department_id=user.department_id, enabled=user.enabled,
        is_super_admin=user.is_super_admin, last_login_at=user.last_login_at,
        department_name=user.department.name if user.department else None,
        roles=[role.name for role in user.roles if role.enabled],
        permissions=sorted(effective_permissions(user)),
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
    ip = request.client.host if request.client else None
    request_id = request.headers.get("X-Request-ID")
    from app.services.audit import record

    try:
        limiter.check(ip)
    except AppError as exc:
        record(
            session, "login_rate_limited", detail={"username": body.username.strip()},
            ip_address=ip, success=False, error_code=exc.code, request_id=request_id,
        )
        raise
    try:
        user = authenticate(session, body.username, body.password)
    except AppError as exc:
        record(
            session, "login_failed", detail={"username": body.username.strip()},
            ip_address=ip, success=False, error_code=exc.code, request_id=request_id,
        )
        raise

    token = create_session_token(session, user, ip, days=settings.auth_session_days)
    record(
        session, "login_success", user=user, detail={"username": user.username},
        ip_address=ip, request_id=request_id,
    )
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
    user = getattr(request.state, "auth_user", None)
    # logout 属于公开端点，中间件可能未解析用户；撤销前按 Cookie 反查退出用户。
    if user is None and token:
        auth_session = find_by_token(session, token)
        if auth_session is not None:
            user = session.get(User, auth_session.user_id)
    revoke_session(session, token or "")
    from app.services.audit import record

    record(
        session, "logout", user=user,
        ip_address=request.client.host if request.client else None,
        request_id=request.headers.get("X-Request-ID"),
    )
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
                .options(
                    selectinload(User.roles).selectinload(Role.permissions),
                    selectinload(User.department),
                )
            )
    if user is None or not user.enabled:
        return AuthMeResponse(authenticated=False)
    return AuthMeResponse(authenticated=True, user=_user_out(user))


@router.get("/permissions", tags=["auth"])
async def list_permissions(request: Request) -> dict:
    """当前用户的有效权限码；前端据此恢复菜单（不能按角色名自行推算）。"""
    user = require_user(current_user(request))
    return {"permissions": sorted(effective_permissions(user))}


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
    return {"items": [{"id": item.id, "name": item.name, "description": item.description, "enabled": item.enabled} for item in rows], "total": len(rows)}
