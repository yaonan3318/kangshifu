"""审计记录服务：写入与查询管理员可读的安全事件。

审计写入是“尽力而为”的：任何失败都只记录日志，不抛出异常，
避免因为审计表问题导致核心业务事务回滚或接口失败。
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AuditLog

logger = logging.getLogger(__name__)

SENSITIVE_LEVELS_EXTERNAL_BLOCKED = ("CONFIDENTIAL", "RESTRICTED")


def record(
    session: Session, action: str, user=None, target_type: str | None = None,
    target_id: uuid.UUID | None = None, detail: dict[str, Any] | None = None,
    ip_address: str | None = None, success: bool = True, error_code: str | None = None,
    request_id: str | None = None, commit: bool = True,
) -> AuditLog | None:
    """写入一条审计日志；失败时记录日志并返回 None，不影响核心业务。"""
    log = AuditLog(
        user_id=user.id if user else None,
        username=(user.username if user else None),
        action=action, target_type=target_type, target_id=target_id,
        detail=detail or {}, ip_address=ip_address,
        success=success, error_code=error_code, request_id=request_id,
    )
    try:
        session.add(log)
        if commit:
            session.commit()
        else:
            session.flush()
    except Exception:
        logger.exception("Failed to write audit log for action=%s", action)
        try:
            session.rollback()
        except Exception:
            logger.exception("Audit rollback failed")
        return None
    return log


def list_logs(
    session: Session, user, action: str | None = None, target_type: str | None = None,
    username: str | None = None, success: bool | None = None,
    created_from: datetime | None = None, created_to: datetime | None = None,
    limit: int = 50, offset: int = 0,
) -> tuple[list[AuditLog], int]:
    if user is None or not user.is_super_admin:
        raise AppError("ADMIN_REQUIRED", "需要管理员权限", 403)
    filters = []
    if action:
        filters.append(AuditLog.action == action)
    if target_type:
        filters.append(AuditLog.target_type == target_type)
    if username:
        filters.append(AuditLog.username.ilike(f"%{username.strip()}%"))
    if success is not None:
        filters.append(AuditLog.success.is_(success))
    if created_from is not None:
        filters.append(AuditLog.created_at >= created_from)
    if created_to is not None:
        filters.append(AuditLog.created_at <= created_to)
    total = session.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    rows = list(session.scalars(
        select(AuditLog).where(*filters).order_by(AuditLog.created_at.desc())
        .offset(offset).limit(limit)
    ))
    return rows, total
