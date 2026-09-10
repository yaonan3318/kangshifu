"""批量导入、进度、重试和继续上传接口。"""
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from sqlalchemy.orm import Session
from app.api.auth import current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.schemas.batches import BatchCreateRequest, BatchDetailResponse, BatchFileResponse, BatchListResponse, BatchResponse
from app.services.audit import record as audit_record
from app.services.batches import BatchService

router = APIRouter(prefix="/api/batches", tags=["batches"])

def get_batch_service(session: Annotated[Session, Depends(get_session)], settings: Annotated[Settings, Depends(get_settings)]) -> BatchService:
    return BatchService(session, settings)


def _meta(request: Request) -> dict:
    return {
        "ip_address": request.client.host if request.client else None,
        "request_id": request.headers.get("X-Request-ID"),
    }

@router.post("", response_model=BatchResponse, status_code=status.HTTP_201_CREATED)
def create_batch(body: BatchCreateRequest, request: Request, service: Annotated[BatchService, Depends(get_batch_service)]):
    batch = service.create(body.name, body.category, body.tags, body.note, body.files, body.knowledge_base_id)
    audit_record(
        service.session, "batch_upload_created", user=current_user(request),
        target_type="batch", target_id=batch.id, detail={"name": body.name}, **_meta(request),
    )
    return service.response(batch)

@router.get("", response_model=BatchListResponse)
def list_batches(service: Annotated[BatchService, Depends(get_batch_service)]):
    items = service.list(); return BatchListResponse(items=[service.response(x) for x in items], total=len(items))

@router.get("/{batch_id}", response_model=BatchDetailResponse)
def get_batch(batch_id: uuid.UUID, service: Annotated[BatchService, Depends(get_batch_service)]):
    return service.response(service.get(batch_id), detail=True)

@router.post("/{batch_id}/files", response_model=BatchFileResponse, status_code=status.HTTP_201_CREATED)
def upload_batch_file(batch_id: uuid.UUID, relative_path: Annotated[str, Form(max_length=2048)], request: Request, file: Annotated[UploadFile, File()], service: Annotated[BatchService, Depends(get_batch_service)]):
    file_row = service.upload(batch_id, relative_path, file)
    audit_record(
        service.session, "batch_upload_resumed", user=current_user(request),
        target_type="batch", target_id=batch_id, detail={"relative_path": relative_path}, **_meta(request),
    )
    return BatchFileResponse.model_validate(file_row)

@router.post("/{batch_id}/files/{file_id}/retry", response_model=BatchFileResponse)
def retry_batch_file(batch_id: uuid.UUID, file_id: uuid.UUID, request: Request, service: Annotated[BatchService, Depends(get_batch_service)]):
    file_row = service.retry(batch_id, file_id)
    audit_record(
        service.session, "batch_upload_resumed", user=current_user(request),
        target_type="batch", target_id=batch_id, detail={"file_id": str(file_id)}, **_meta(request),
    )
    return BatchFileResponse.model_validate(file_row)

@router.post("/{batch_id}/files/{file_id}/ignore", response_model=BatchFileResponse)
def ignore_batch_file(batch_id: uuid.UUID, file_id: uuid.UUID, service: Annotated[BatchService, Depends(get_batch_service)]):
    return BatchFileResponse.model_validate(service.ignore(batch_id, file_id))

@router.post("/{batch_id}/cancel", response_model=BatchResponse)
def cancel_batch(batch_id: uuid.UUID, request: Request, service: Annotated[BatchService, Depends(get_batch_service)]):
    batch = service.cancel(batch_id)
    audit_record(
        service.session, "batch_upload_failed", user=current_user(request),
        target_type="batch", target_id=batch_id, detail={"reason": "cancelled"},
        success=False, error_code="BATCH_CANCELLED", **_meta(request),
    )
    return service.response(batch)
