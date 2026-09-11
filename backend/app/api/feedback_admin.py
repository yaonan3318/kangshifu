"""管理员反馈处理 API：队列、详情、状态流转、分配、复验与统计。"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import AppError
from app.services.audit import audit_action
from app.services.feedback import CASE_STATUS_VALUES, FeedbackService
from app.services.feedback_ranking import FeedbackRankingService
from app.services.feedback_verification import FeedbackVerificationService
from app.services.rbac import require_permission

router = APIRouter(prefix="/api/admin/feedback", tags=["feedback-admin"])

FEEDBACK_VIEW = "FEEDBACK_VIEW"
FEEDBACK_MANAGE = "FEEDBACK_MANAGE"
FEEDBACK_ASSIGN = "FEEDBACK_ASSIGN"
FEEDBACK_VERIFY = "FEEDBACK_VERIFY"
FEEDBACK_STATISTICS = "FEEDBACK_STATISTICS"


class CaseUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(PENDING|PROCESSING|WAIT_VERIFY|RESOLVED|IGNORED)$")
    priority: str | None = Field(default=None, pattern="^(LOW|NORMAL|HIGH|URGENT)$")
    admin_note: str | None = Field(default=None, max_length=4000)
    conclusion: str | None = Field(default=None, max_length=4000)
    fix_document_id: uuid.UUID | None = None
    fix_config_version_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


class AssignBody(BaseModel):
    assignee_id: uuid.UUID | None = None
    priority: str | None = Field(default=None, pattern="^(LOW|NORMAL|HIGH|URGENT)$")
    note: str | None = Field(default=None, max_length=2000)


class VerifyBody(BaseModel):
    conclusion: str | None = Field(default=None, max_length=4000)


def _service(session: Session, settings: Settings) -> FeedbackService:
    return FeedbackService(session, settings)


@router.get("/cases")
def list_cases(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    status: list[str] | None = Query(default=None),
    feedback_type: str | None = None,
    knowledge_base_id: uuid.UUID | None = None,
    assistant_id: uuid.UUID | None = None,
    assignee_id: uuid.UUID | None = None,
    keyword: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict:
    require_permission(current_user(request), FEEDBACK_VIEW)
    items, total = _service(session, settings).list_cases(
        statuses=status, feedback_type=feedback_type, knowledge_base_id=knowledge_base_id,
        assistant_id=assistant_id, assignee_id=assignee_id, keyword=keyword,
        created_from=created_from, created_to=created_to, page=page, page_size=page_size,
    )
    return {"items": items, "page": page, "page_size": page_size, "total": total,
            "status_options": CASE_STATUS_VALUES}


@router.get("/cases/{case_id}")
def get_case(
    case_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    require_permission(current_user(request), FEEDBACK_VIEW)
    return _service(session, settings).case_detail(case_id)


@router.patch("/cases/{case_id}")
def update_case(
    case_id: uuid.UUID,
    body: CaseUpdate,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    user = require_permission(current_user(request), FEEDBACK_MANAGE)
    service = _service(session, settings)
    with audit_action(
        session, "feedback_case_updated", user=user, target_type="feedback_case", target_id=case_id,
    ) as audit:
        case = service.update_case(
            case_id, user, status=body.status, priority=body.priority, admin_note=body.admin_note,
            conclusion=body.conclusion, fix_document_id=body.fix_document_id,
            fix_config_version_id=body.fix_config_version_id, note=body.note,
        )
        audit.detail = {"status": case.status.value, "priority": case.priority.value}
    return service.case_detail(case_id)


@router.post("/cases/{case_id}/assign")
def assign_case(
    case_id: uuid.UUID,
    body: AssignBody,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    user = require_permission(current_user(request), FEEDBACK_ASSIGN)
    service = _service(session, settings)
    with audit_action(
        session, "feedback_case_assigned", user=user, target_type="feedback_case", target_id=case_id,
    ) as audit:
        case = service.assign_case(
            case_id, user, assignee_id=body.assignee_id, priority=body.priority, note=body.note,
        )
        audit.detail = {
            "assignee_id": str(case.assignee_id) if case.assignee_id else None,
            "priority": case.priority.value,
        }
    return service.case_detail(case_id)


@router.post("/cases/{case_id}/verify")
async def verify_case(
    case_id: uuid.UUID,
    body: VerifyBody,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    user = require_permission(current_user(request), FEEDBACK_VERIFY)
    service = _service(session, settings)
    with audit_action(
        session, "feedback_case_verified", user=user, target_type="feedback_case", target_id=case_id,
    ) as audit:
        run = await FeedbackVerificationService(session, settings).verify(
            case_id, user, conclusion=body.conclusion,
        )
        audit.detail = {"verification_id": str(run.id), "status": run.status.value}
    return service.case_detail(case_id)


@router.get("/statistics")
def statistics(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    knowledge_base_id: uuid.UUID | None = None,
    assistant_id: uuid.UUID | None = None,
    config_version_id: uuid.UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> dict:
    require_permission(current_user(request), FEEDBACK_STATISTICS)
    result = _service(session, settings).statistics(
        knowledge_base_id=knowledge_base_id, assistant_id=assistant_id,
        config_version_id=config_version_id, created_from=created_from, created_to=created_to,
    )
    ranking = FeedbackRankingService(session, settings, config=None)
    result["enabled"] = ranking.enabled
    result["parameters"] = ranking._parameters()
    result["aggregates"] = ranking.aggregate_statistics()
    return result


@router.get("/config-comparison")
def config_comparison(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    left: uuid.UUID = Query(),
    right: uuid.UUID = Query(),
) -> dict:
    require_permission(current_user(request), FEEDBACK_STATISTICS)
    service = _service(session, settings)
    left_stats = service.statistics(config_version_id=left)["overall"]
    right_stats = service.statistics(config_version_id=right)["overall"]
    keys = sorted(set(left_stats) | set(right_stats))
    differences = []
    for key in keys:
        left_value = left_stats.get(key)
        right_value = right_stats.get(key)
        delta = None
        if isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)):
            delta = round(float(right_value) - float(left_value), 4)
        differences.append({"key": key, "left": left_value, "right": right_value, "delta": delta})
    return {"left": left_stats, "right": right_stats, "differences": differences}
