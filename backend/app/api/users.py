"""用户管理 API（仅超级管理员）。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.db import get_session
from app.schemas.identity import (
    ResetPasswordRequest, UserCreateRequest, UserListResponse, UserOut, UserUpdateRequest,
)
from app.services import identity
from app.services.audit import audit_action, record as audit_record
from app.services.rbac import require_permission

router = APIRouter(prefix="/api/users", tags=["users"])

IDENTITY_MANAGE = "IDENTITY_MANAGE"


def _request_meta(request: Request) -> dict:
    return {
        "ip_address": request.client.host if request.client else None,
        "request_id": request.headers.get("X-Request-ID"),
    }


@router.get("", response_model=UserListResponse)
def list_users(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    search: str | None = None,
    department_id: uuid.UUID | None = None,
    role_id: uuid.UUID | None = None,
    enabled: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> UserListResponse:
    require_permission(current_user(request), IDENTITY_MANAGE)
    rows, total = identity.list_users(
        session, search=search, department_id=department_id, role_id=role_id,
        enabled=enabled, page=page, page_size=page_size,
    )
    return UserListResponse(
        items=[UserOut(**identity.user_payload(row)) for row in rows],
        page=page, page_size=page_size, total=total,
    )


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreateRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> UserOut:
    admin = require_permission(current_user(request), IDENTITY_MANAGE)
    with audit_action(
        session, "user_created", user=admin, target_type="user", **_request_meta(request),
    ) as audit:
        user = identity.create_user(
            session, username=body.username, display_name=body.display_name, password=body.password,
            department_id=body.department_id, role_ids=body.role_ids,
            is_super_admin=body.is_super_admin, enabled=body.enabled,
        )
        audit.id = user.id
        audit.detail = {"username": user.username, "is_super_admin": user.is_super_admin}
    return UserOut(**identity.user_payload(user))


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> UserOut:
    require_permission(current_user(request), IDENTITY_MANAGE)
    return UserOut(**identity.user_payload(identity.load_user(session, user_id)))


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    body: UserUpdateRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> UserOut:
    admin = require_permission(current_user(request), IDENTITY_MANAGE)
    with audit_action(
        session, "user_updated", user=admin, target_type="user", target_id=user_id,
        detail={"fields": sorted(body.model_fields_set)}, **_request_meta(request),
    ):
        user = identity.update_user(
            session, user_id, current=admin,
            display_name=body.display_name,
            department_id=body.department_id,
            department_set="department_id" in body.model_fields_set,
            role_ids=body.role_ids, is_super_admin=body.is_super_admin, enabled=body.enabled,
        )
    if body.role_ids is not None:
        audit_record(
            session, "role_assignment_changed", user=admin, target_type="user", target_id=user.id,
            detail={"role_ids": [str(item) for item in body.role_ids]}, **_request_meta(request),
        )
    return UserOut(**identity.user_payload(user))


@router.post("/{user_id}/enable", response_model=UserOut)
def enable_user(
    user_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> UserOut:
    admin = require_permission(current_user(request), IDENTITY_MANAGE)
    with audit_action(
        session, "user_enabled", user=admin, target_type="user", target_id=user_id,
        **_request_meta(request),
    ):
        user = identity.set_enabled(session, user_id, True, admin)
    return UserOut(**identity.user_payload(user))


@router.post("/{user_id}/disable", response_model=UserOut)
def disable_user(
    user_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> UserOut:
    admin = require_permission(current_user(request), IDENTITY_MANAGE)
    with audit_action(
        session, "user_disabled", user=admin, target_type="user", target_id=user_id,
        **_request_meta(request),
    ):
        user = identity.set_enabled(session, user_id, False, admin)
    return UserOut(**identity.user_payload(user))


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: uuid.UUID,
    body: ResetPasswordRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    admin = require_permission(current_user(request), IDENTITY_MANAGE)
    with audit_action(
        session, "password_reset", user=admin, target_type="user", target_id=user_id,
        **_request_meta(request),
    ) as audit:
        user = identity.reset_password(session, user_id, body.new_password)
        audit.detail = {"username": user.username}
    return {"ok": True, "sessions_revoked": True}
