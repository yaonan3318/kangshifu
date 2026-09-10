"""知识缺口中心 API：查看、指派、补充资料、重跑与前后对比（STATS_VIEW）。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.schemas.knowledge_gap import (
    KnowledgeGapListResponse, KnowledgeGapOut, KnowledgeGapRerunResponse, KnowledgeGapStatsResponse,
    KnowledgeGapUpdate,
)
from app.services.knowledge_gaps import KnowledgeGapService
from app.services.rbac import require_permission

router = APIRouter(prefix="/api/knowledge-gaps", tags=["knowledge-gaps"])

STATS_VIEW = "STATS_VIEW"


def get_service(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> KnowledgeGapService:
    user = require_permission(current_user(request), STATS_VIEW)
    return KnowledgeGapService(session, settings, user=user)


@router.get("", response_model=KnowledgeGapListResponse)
def list_gaps(
    service: Annotated[KnowledgeGapService, Depends(get_service)],
    status: str | None = None,
    reason: str | None = None,
    assignee_user_id: uuid.UUID | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    items, total = service.list(
        status=status, reason=reason, assignee_user_id=assignee_user_id,
        page=page, page_size=page_size,
    )
    return KnowledgeGapListResponse(
        items=[KnowledgeGapOut.model_validate(item) for item in items],
        page=page, page_size=page_size, total=total,
    )


@router.get("/statistics", response_model=KnowledgeGapStatsResponse)
def gap_statistics(service: Annotated[KnowledgeGapService, Depends(get_service)]):
    return KnowledgeGapStatsResponse(**service.statistics())


@router.get("/{gap_id}", response_model=KnowledgeGapOut)
def get_gap(gap_id: uuid.UUID, service: Annotated[KnowledgeGapService, Depends(get_service)]):
    return KnowledgeGapOut.model_validate(service.get(gap_id))


@router.patch("/{gap_id}", response_model=KnowledgeGapOut)
def update_gap(
    gap_id: uuid.UUID,
    body: KnowledgeGapUpdate,
    service: Annotated[KnowledgeGapService, Depends(get_service)],
):
    value = service.update(
        gap_id, status=body.status,
        assignee_user_id=body.assignee_user_id,
        assignee_set="assignee_user_id" in body.model_fields_set,
        linked_document_ids=body.linked_document_ids,
        note=body.note, note_set="note" in body.model_fields_set,
    )
    return KnowledgeGapOut.model_validate(value)


@router.post("/{gap_id}/rerun", response_model=KnowledgeGapRerunResponse)
async def rerun_gap(gap_id: uuid.UUID, service: Annotated[KnowledgeGapService, Depends(get_service)]):
    return KnowledgeGapRerunResponse(**await service.rerun(gap_id))
