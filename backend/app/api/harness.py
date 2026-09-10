"""Harness 环境探测、任务恢复和写操作审批接口。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.answer import encode_sse
from app.api.auth import current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.harness.kubernetes import KubectlClient
from app.schemas.harness import ApprovalConfirmRequest, ApprovalRejectRequest, HarnessApprovalResponse, HarnessStatusResponse, HarnessTaskResponse
from app.services.audit import record as audit_record
from app.services.harness import HarnessService
from app.services.harness_approvals import ApprovalService
from app.services.permissions import require_admin

router = APIRouter(prefix="/api/harness", tags=["harness"])


def _meta(request: Request) -> dict:
    return {
        "ip_address": request.client.host if request.client else None,
        "request_id": request.headers.get("X-Request-ID"),
    }


@router.get("/status", response_model=HarnessStatusResponse)
def status(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> HarnessStatusResponse:
    require_admin(current_user(request))
    client = KubectlClient(settings)
    return HarnessStatusResponse(enabled=bool(settings.allowed_k8s_contexts), kubectl_available=client.available, contexts=settings.allowed_k8s_contexts, max_steps=settings.harness_max_steps, timeout_seconds=settings.harness_timeout_seconds)


@router.get("/namespaces", response_model=list[str])
async def namespaces(request: Request, context: Annotated[str, Query()], settings: Annotated[Settings, Depends(get_settings)]) -> list[str]:
    require_admin(current_user(request))
    result = await KubectlClient(settings).run(context, ["get", "namespaces", "-o", "json"])
    return [item["metadata"]["name"] for item in result.json().get("items", [])]


@router.get("/tasks/{task_id}", response_model=HarnessTaskResponse)
def task(task_id: uuid.UUID, request: Request, session: Annotated[Session, Depends(get_session)], settings: Annotated[Settings, Depends(get_settings)]) -> HarnessTaskResponse:
    require_admin(current_user(request))
    return HarnessTaskResponse.model_validate(HarnessService(session, settings).get_task(task_id))


@router.post("/tasks/{task_id}/resume")
def resume(task_id: uuid.UUID, request: Request, session: Annotated[Session, Depends(get_session)], settings: Annotated[Settings, Depends(get_settings)], use_deepseek: bool = False) -> StreamingResponse:
    admin = require_admin(current_user(request))
    service = HarnessService(session, settings, user=admin)
    audit_record(
        session, "harness_started", user=admin, target_type="harness_task", target_id=task_id,
        detail={"use_deepseek": use_deepseek}, **_meta(request),
    )
    return StreamingResponse((encode_sse(event) async for event in service.resume(task_id, use_deepseek)), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/approvals/{approval_id}/confirm", response_model=HarnessApprovalResponse)
async def confirm(approval_id: uuid.UUID, body: ApprovalConfirmRequest, request: Request, session: Annotated[Session, Depends(get_session)], settings: Annotated[Settings, Depends(get_settings)]) -> HarnessApprovalResponse:
    admin = require_admin(current_user(request))
    result = HarnessApprovalResponse.model_validate(await ApprovalService(session, settings).confirm(approval_id, body.confirmation_context))
    audit_record(
        session, "harness_approval_confirmed", user=admin, target_type="harness_approval",
        target_id=approval_id, detail={"status": result.status}, **_meta(request),
    )
    return result


@router.post("/approvals/{approval_id}/reject", response_model=HarnessApprovalResponse)
def reject(approval_id: uuid.UUID, body: ApprovalRejectRequest, request: Request, session: Annotated[Session, Depends(get_session)], settings: Annotated[Settings, Depends(get_settings)]) -> HarnessApprovalResponse:
    admin = require_admin(current_user(request))
    result = HarnessApprovalResponse.model_validate(ApprovalService(session, settings).reject(approval_id, body.reason))
    audit_record(
        session, "harness_approval_rejected", user=admin, target_type="harness_approval",
        target_id=approval_id, detail={"reason": body.reason}, **_meta(request),
    )
    return result
