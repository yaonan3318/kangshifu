"""审计记录服务：写入与查询管理员可读的安全事件。

审计写入是“尽力而为”的：任何失败都只记录日志，不抛出异常，
避免因为审计表问题导致核心业务事务回滚或接口失败。
"""

import logging
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.errors import AppError
from app.models import AuditLog

logger = logging.getLogger(__name__)

SENSITIVE_LEVELS_EXTERNAL_BLOCKED = ("CONFIDENTIAL", "RESTRICTED")


@dataclass
class AuditTarget:
    """审计上下文：允许调用方在操作完成后回填目标 ID 与详情。"""
    id: uuid.UUID | None = None
    detail: dict[str, Any] | None = None


def _user_fields(user) -> tuple[uuid.UUID | None, str | None]:
    try:
        return (user.id if user else None, user.username if user else None)
    except Exception:  # pragma: no cover - 防御已过期/脱离会话的 ORM 实例
        return None, None


def record(
    session: Session | None, action: str, user=None, target_type: str | None = None,
    target_id: uuid.UUID | None = None, detail: dict[str, Any] | None = None,
    ip_address: str | None = None, success: bool = True, error_code: str | None = None,
    request_id: str | None = None, commit: bool = True,
) -> AuditLog | None:
    """写入一条审计日志；失败时记录日志并返回 None，不影响核心业务。

    ``session`` 为 None 时使用独立 Session，避免污染/回滚调用方的核心事务。
    """
    user_id, username = _user_fields(user)
    log = AuditLog(
        user_id=user_id, username=username,
        action=action, target_type=target_type, target_id=target_id,
        detail=detail or {}, ip_address=ip_address,
        success=success, error_code=error_code, request_id=request_id,
    )
    owns_session = session is None
    target = None
    try:
        target = session if session is not None else SessionLocal()
        target.add(log)
        if commit:
            target.commit()
        else:
            target.flush()
    except Exception:
        logger.exception("Failed to write audit log for action=%s", action)
        if target is not None:
            try:
                target.rollback()
            except Exception:
                logger.exception("Audit rollback failed")
        return None
    finally:
        if owns_session and target is not None:
            target.close()
    return log


def _safe_record(
    session: Session | None, action: str, user, target_type: str | None,
    audit: AuditTarget, ip_address: str | None, request_id: str | None,
    success: bool, error_code: str | None, independent: bool,
) -> None:
    record(
        None if independent else session, action, user=user, target_type=target_type,
        target_id=audit.id, detail=audit.detail, ip_address=ip_address,
        success=success, error_code=error_code, request_id=request_id,
    )


@contextmanager
def audit_action(
    session: Session | None, action: str, *, user=None, target_type: str | None = None,
    target_id: uuid.UUID | None = None, detail: dict[str, Any] | None = None,
    ip_address: str | None = None, request_id: str | None = None, independent: bool = True,
):
    """统一记录关键写操作的成败审计，避免每个接口重复 try/except。

    - 成功：操作完成后写入 success=True；
    - 业务失败（AppError）：写入 success=False 与 error_code 后原样抛出；
    - 未知异常：写入 success=False / error_code=INTERNAL_ERROR 后原样抛出；
    - independent=True（默认）使用独立 Session，审计写入失败不会回滚核心业务。

    调用方可回填延迟才知道的目标与详情::

        with audit_action(session, "user_created", user=admin, target_type="user") as audit:
            row = identity.create_user(...)
            audit.id = row.id
            audit.detail = {"username": row.username}
    """
    audit = AuditTarget(id=target_id, detail=detail)
    try:
        yield audit
    except AppError as exc:
        _safe_record(session, action, user, target_type, audit, ip_address, request_id, False, exc.code, independent)
        raise
    except Exception:
        _safe_record(session, action, user, target_type, audit, ip_address, request_id, False, "INTERNAL_ERROR", independent)
        raise
    else:
        _safe_record(session, action, user, target_type, audit, ip_address, request_id, True, None, independent)


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
