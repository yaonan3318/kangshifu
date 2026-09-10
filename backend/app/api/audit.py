"""审计日志查询接口（仅管理员）。"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.audit import AuditLogListResponse, AuditLogOut
from app.services.audit import list_logs

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/logs", response_model=AuditLogListResponse)
def query_logs(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    action: str | None = None,
    target_type: str | None = None,
    username: str | None = None,
    success: bool | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> AuditLogListResponse:
    rows, total = list_logs(
        session, getattr(request.state, "auth_user", None),
        action=action, target_type=target_type, username=username, success=success,
        created_from=created_from, created_to=created_to,
        limit=page_size, offset=(page - 1) * page_size,
    )
    items = [AuditLogOut.model_validate(item) for item in rows]
    return AuditLogListResponse(items=items, page=page, page_size=page_size, total=total)
