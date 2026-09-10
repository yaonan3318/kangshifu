"""部门管理 API：树形读取与超级管理员写操作。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.db import get_session
from app.schemas.identity import DepartmentCreateRequest, DepartmentOut, DepartmentTreeNode, DepartmentUpdateRequest
from app.services import identity
from app.services.audit import record as audit_record
from app.services.permissions import require_admin, require_user

router = APIRouter(prefix="/api/departments", tags=["departments"])


def _request_meta(request: Request) -> dict:
    return {
        "ip_address": request.client.host if request.client else None,
        "request_id": request.headers.get("X-Request-ID"),
    }


@router.get("/tree", response_model=list[DepartmentTreeNode])
def department_tree(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> list[DepartmentTreeNode]:
    require_user(current_user(request))
    return [DepartmentTreeNode(**node) for node in identity.department_tree(session)]


@router.get("/{department_id}", response_model=DepartmentOut)
def get_department(
    department_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> DepartmentOut:
    require_user(current_user(request))
    department = identity.load_department(session, department_id)
    return DepartmentOut(**identity.department_payload(session, department))


@router.post("", response_model=DepartmentOut, status_code=201)
def create_department(
    body: DepartmentCreateRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> DepartmentOut:
    admin = require_admin(current_user(request))
    department = identity.create_department(
        session, name=body.name, parent_id=body.parent_id, enabled=body.enabled,
    )
    audit_record(
        session, "department_created", user=admin, target_type="department", target_id=department.id,
        detail={"name": department.name, "parent_id": str(department.parent_id) if department.parent_id else None},
        **_request_meta(request),
    )
    return DepartmentOut(**identity.department_payload(session, department))


@router.patch("/{department_id}", response_model=DepartmentOut)
def update_department(
    department_id: uuid.UUID,
    body: DepartmentUpdateRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> DepartmentOut:
    admin = require_admin(current_user(request))
    department = identity.update_department(
        session, department_id, name=body.name, parent_id=body.parent_id,
        parent_set="parent_id" in body.model_fields_set, enabled=body.enabled,
    )
    audit_record(
        session, "department_updated", user=admin, target_type="department", target_id=department.id,
        detail={"fields": sorted(body.model_fields_set)}, **_request_meta(request),
    )
    return DepartmentOut(**identity.department_payload(session, department))


@router.post("/{department_id}/enable", response_model=DepartmentOut)
def enable_department(
    department_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> DepartmentOut:
    admin = require_admin(current_user(request))
    department = identity.set_department_enabled(session, department_id, True)
    audit_record(
        session, "department_enabled", user=admin, target_type="department", target_id=department.id,
        detail={"name": department.name}, **_request_meta(request),
    )
    return DepartmentOut(**identity.department_payload(session, department))


@router.post("/{department_id}/disable", response_model=DepartmentOut)
def disable_department(
    department_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> DepartmentOut:
    admin = require_admin(current_user(request))
    department = identity.set_department_enabled(session, department_id, False)
    affected = identity.department_user_count(session, department.id)
    audit_record(
        session, "department_disabled", user=admin, target_type="department", target_id=department.id,
        detail={"name": department.name, "affected_users": affected}, **_request_meta(request),
    )
    return DepartmentOut(**identity.department_payload(session, department))
