"""审计记录服务：写入与查询管理员可读的安全事件。"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AuditLog

SENSITIVE_LEVELS_EXTERNAL_BLOCKED = ("CONFIDENTIAL", "RESTRICTED")


def record(
    session: Session, action: str, user=None, target_type: str | None = None,
    target_id: uuid.UUID | None = None, detail: dict[str, Any] | None = None,
    ip_address: str | None = None, commit: bool = True,
) -> AuditLog:
    log = AuditLog(
        user_id=user.id if user else None,
        username=(user.username if user else None),
        action=action, target_type=target_type, target_id=target_id,
        detail=detail or {}, ip_address=ip_address,
    )
    session.add(log)
    if commit:
        session.commit()
    return log


def list_logs(
    session: Session, user, action: str | None = None, target_type: str | None = None,
    limit: int = 50, offset: int = 0,
) -> tuple[list[AuditLog], int]:
    if user is None or not user.is_super_admin:
        raise AppError("ADMIN_REQUIRED", "需要管理员权限", 403)
    filters = []
    if action:
        filters.append(AuditLog.action == action)
    if target_type:
        filters.append(AuditLog.target_type == target_type)
    total = session.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    rows = list(session.scalars(
        select(AuditLog).where(*filters).order_by(AuditLog.created_at.desc())
        .offset(offset).limit(limit)
    ))
    return rows, total
