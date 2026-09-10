"""角色管理 API：角色 CRUD、启停与成员分配（仅超级管理员）。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.db import get_session
from app.models import Document, DocumentAcl, SubjectType
from app.schemas.identity import RoleCreateRequest, RoleListResponse, RoleOut, RoleUpdateRequest, RoleUsersRequest
from app.services import identity
from app.services.audit import audit_action, record as audit_record
from app.services.rbac import permission_catalog, require_permission

router = APIRouter(prefix="/api/roles", tags=["roles"])

IDENTITY_MANAGE = "IDENTITY_MANAGE"


def _request_meta(request: Request) -> dict:
    return {
        "ip_address": request.client.host if request.client else None,
        "request_id": request.headers.get("X-Request-ID"),
    }


def _role_out(session: Session, role) -> RoleOut:
    return RoleOut(**identity.role_payload(session, role))


@router.get("", response_model=RoleListResponse)
def list_roles(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> RoleListResponse:
    require_permission(current_user(request), IDENTITY_MANAGE)
    items, total = identity.list_roles(session, page=page, page_size=page_size)
    return RoleListResponse(items=[RoleOut(**item) for item in items], page=page, page_size=page_size, total=total)


@router.get("/permissions")
def list_permission_catalog(request: Request) -> dict:
    """功能权限码目录（按类别），供角色编辑页面渲染勾选项。"""
    require_permission(current_user(request), IDENTITY_MANAGE)
    return {"categories": [
        {"key": "basic", "label": "基础使用"},
        {"key": "document", "label": "资料管理"},
        {"key": "operations", "label": "系统运营"},
    ], "items": [item for item in permission_catalog() if item["category"] != "harness"]}


@router.post("", response_model=RoleOut, status_code=201)
def create_role(
    body: RoleCreateRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> RoleOut:
    admin = require_permission(current_user(request), IDENTITY_MANAGE)
    with audit_action(
        session, "role_created", user=admin, target_type="role", **_request_meta(request),
    ) as audit:
        role = identity.create_role(
            session, name=body.name, description=body.description, enabled=body.enabled,
            permissions=body.permissions,
        )
        audit.id = role.id
        audit.detail = {"name": role.name, "permissions": sorted(permission.code for permission in role.permissions)}
    if body.permissions:
        audit_record(
            session, "role_permissions_changed", user=admin, target_type="role", target_id=role.id,
            detail={"added": sorted(body.permissions), "removed": []}, **_request_meta(request),
        )
    return _role_out(session, role)


@router.get("/{role_id}", response_model=RoleOut)
def get_role(
    role_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> RoleOut:
    require_permission(current_user(request), IDENTITY_MANAGE)
    return _role_out(session, identity.load_role(session, role_id))


@router.patch("/{role_id}", response_model=RoleOut)
def update_role(
    role_id: uuid.UUID,
    body: RoleUpdateRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> RoleOut:
    admin = require_permission(current_user(request), IDENTITY_MANAGE)
    with audit_action(
        session, "role_updated", user=admin, target_type="role", target_id=role_id,
        detail={"fields": sorted(body.model_fields_set)}, **_request_meta(request),
    ):
        role = identity.update_role(
            session, role_id, name=body.name, description=body.description,
            description_set="description" in body.model_fields_set, enabled=body.enabled,
        )
    if body.permissions is not None:
        diff = identity.set_role_permissions(session, role, body.permissions)
        audit_record(
            session, "role_permissions_changed", user=admin, target_type="role", target_id=role.id,
            detail=diff, **_request_meta(request),
        )
        role = identity.load_role(session, role_id)
    return _role_out(session, role)


@router.post("/{role_id}/enable", response_model=RoleOut)
def enable_role(
    role_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> RoleOut:
    admin = require_permission(current_user(request), IDENTITY_MANAGE)
    with audit_action(
        session, "role_enabled", user=admin, target_type="role", target_id=role_id,
        **_request_meta(request),
    ):
        role = identity.set_role_enabled(session, role_id, True)
    return _role_out(session, role)


@router.post("/{role_id}/disable", response_model=RoleOut)
def disable_role(
    role_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> RoleOut:
    admin = require_permission(current_user(request), IDENTITY_MANAGE)
    with audit_action(
        session, "role_disabled", user=admin, target_type="role", target_id=role_id,
        **_request_meta(request),
    ):
        role = identity.set_role_enabled(session, role_id, False)
    return _role_out(session, role)


@router.put("/{role_id}/users", response_model=RoleOut)
def set_role_users(
    role_id: uuid.UUID,
    body: RoleUsersRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> RoleOut:
    admin = require_permission(current_user(request), IDENTITY_MANAGE)
    with audit_action(
        session, "role_assignment_changed", user=admin, target_type="role", target_id=role_id,
        detail={"user_ids": [str(item) for item in body.user_ids]}, **_request_meta(request),
    ):
        role = identity.set_role_users(session, role_id, body.user_ids)
    return _role_out(session, role)


@router.get("/{role_id}/documents")
def role_documents(
    role_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    require_permission(current_user(request), IDENTITY_MANAGE)
    identity.load_role(session, role_id)
    rows = session.execute(
        select(Document.id, Document.original_name, Document.visibility, DocumentAcl.permission)
        .join(DocumentAcl, DocumentAcl.document_id == Document.id)
        .where(DocumentAcl.subject_type == SubjectType.ROLE, DocumentAcl.subject_id == role_id)
        .order_by(Document.original_name)
    ).all()
    return {"items": [
        {
            "document_id": row[0], "document_name": row[1],
            "visibility": row[2].value if hasattr(row[2], "value") else row[2],
            "permission": row[3].value if hasattr(row[3], "value") else row[3],
        }
        for row in rows
    ]}
