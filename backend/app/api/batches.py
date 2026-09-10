"""批量导入、进度、重试和继续上传接口。"""
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from sqlalchemy.orm import Session
from app.api.auth import current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import AppError
from app.schemas.batches import BatchCreateRequest, BatchDetailResponse, BatchFileResponse, BatchListResponse, BatchResponse
from app.services.audit import audit_action, record as audit_record
from app.services.batches import BatchService
from app.services.rbac import require_permission

router = APIRouter(prefix="/api/batches", tags=["batches"])

DOCUMENT_UPLOAD = "DOCUMENT_UPLOAD"
DOCUMENT_VIEW = "DOCUMENT_VIEW"

def get_batch_service(session: Annotated[Session, Depends(get_session)], settings: Annotated[Settings, Depends(get_settings)]) -> BatchService:
    return BatchService(session, settings)


def _meta(request: Request) -> dict:
    return {
        "ip_address": request.client.host if request.client else None,
        "request_id": request.headers.get("X-Request-ID"),
    }

@router.post("", response_model=BatchResponse, status_code=status.HTTP_201_CREATED)
def create_batch(body: BatchCreateRequest, request: Request, service: Annotated[BatchService, Depends(get_batch_service)]):
    require_permission(current_user(request), DOCUMENT_UPLOAD)
    with audit_action(
        service.session, "batch_upload_created", user=current_user(request),
        target_type="batch", detail={"name": body.name}, **_meta(request),
    ) as audit:
        batch = service.create(body.name, body.category, body.tags, body.note, body.files, body.knowledge_base_id)
        audit.id = batch.id
    return service.response(batch)

@router.get("", response_model=BatchListResponse)
def list_batches(request: Request, service: Annotated[BatchService, Depends(get_batch_service)]):
    require_permission(current_user(request), DOCUMENT_VIEW)
    items = service.list(); return BatchListResponse(items=[service.response(x) for x in items], total=len(items))

@router.get("/{batch_id}", response_model=BatchDetailResponse)
def get_batch(batch_id: uuid.UUID, request: Request, service: Annotated[BatchService, Depends(get_batch_service)]):
    require_permission(current_user(request), DOCUMENT_VIEW)
    return service.response(service.get(batch_id), detail=True)

@router.post("/{batch_id}/files", response_model=BatchFileResponse, status_code=status.HTTP_201_CREATED)
def upload_batch_file(batch_id: uuid.UUID, relative_path: Annotated[str, Form(max_length=2048)], request: Request, file: Annotated[UploadFile, File()], service: Annotated[BatchService, Depends(get_batch_service)]):
    require_permission(current_user(request), DOCUMENT_UPLOAD)
    with audit_action(
        service.session, "batch_upload_resumed", user=current_user(request),
        target_type="batch", target_id=batch_id, detail={"relative_path": relative_path}, **_meta(request),
    ):
        file_row = service.upload(batch_id, relative_path, file)
    return BatchFileResponse.model_validate(file_row)

@router.post("/{batch_id}/files/{file_id}/retry", response_model=BatchFileResponse)
def retry_batch_file(batch_id: uuid.UUID, file_id: uuid.UUID, request: Request, service: Annotated[BatchService, Depends(get_batch_service)]):
    require_permission(current_user(request), DOCUMENT_UPLOAD)
    with audit_action(
        service.session, "batch_upload_resumed", user=current_user(request),
        target_type="batch", target_id=batch_id, detail={"file_id": str(file_id)}, **_meta(request),
    ):
        file_row = service.retry(batch_id, file_id)
    return BatchFileResponse.model_validate(file_row)

@router.post("/{batch_id}/files/{file_id}/ignore", response_model=BatchFileResponse)
def ignore_batch_file(batch_id: uuid.UUID, file_id: uuid.UUID, request: Request, service: Annotated[BatchService, Depends(get_batch_service)]):
    require_permission(current_user(request), DOCUMENT_UPLOAD)
    with audit_action(
        service.session, "batch_file_ignored", user=current_user(request),
        target_type="batch", target_id=batch_id, detail={"file_id": str(file_id)}, **_meta(request),
    ):
        file_row = service.ignore(batch_id, file_id)
    return BatchFileResponse.model_validate(file_row)

@router.post("/{batch_id}/cancel", response_model=BatchResponse)
def cancel_batch(batch_id: uuid.UUID, request: Request, service: Annotated[BatchService, Depends(get_batch_service)]):
    require_permission(current_user(request), DOCUMENT_UPLOAD)
    # 取消属于批次失败事件：成功后仍以 success=False / BATCH_CANCELLED 记录。
    try:
        batch = service.cancel(batch_id)
    except AppError as exc:
        audit_record(
            None, "batch_upload_failed", user=current_user(request),
            target_type="batch", target_id=batch_id, detail={"reason": "cancel_failed"},
            success=False, error_code=exc.code, **_meta(request),
        )
        raise
    audit_record(
        None, "batch_upload_failed", user=current_user(request),
        target_type="batch", target_id=batch_id, detail={"reason": "cancelled"},
        success=False, error_code="BATCH_CANCELLED", **_meta(request),
    )
    return service.response(batch)
