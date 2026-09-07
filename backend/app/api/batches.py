"""批量导入、进度、重试和继续上传接口。"""
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session
from app.config import Settings, get_settings
from app.db import get_session
from app.schemas.batches import BatchCreateRequest, BatchDetailResponse, BatchFileResponse, BatchListResponse, BatchResponse
from app.services.batches import BatchService

router = APIRouter(prefix="/api/batches", tags=["batches"])

def get_batch_service(session: Annotated[Session, Depends(get_session)], settings: Annotated[Settings, Depends(get_settings)]) -> BatchService:
    return BatchService(session, settings)

@router.post("", response_model=BatchResponse, status_code=status.HTTP_201_CREATED)
def create_batch(body: BatchCreateRequest, service: Annotated[BatchService, Depends(get_batch_service)]):
    return service.response(service.create(body.name, body.category, body.tags, body.note, body.files))

@router.get("", response_model=BatchListResponse)
def list_batches(service: Annotated[BatchService, Depends(get_batch_service)]):
    items = service.list(); return BatchListResponse(items=[service.response(x) for x in items], total=len(items))

@router.get("/{batch_id}", response_model=BatchDetailResponse)
def get_batch(batch_id: uuid.UUID, service: Annotated[BatchService, Depends(get_batch_service)]):
    return service.response(service.get(batch_id), detail=True)

@router.post("/{batch_id}/files", response_model=BatchFileResponse, status_code=status.HTTP_201_CREATED)
def upload_batch_file(batch_id: uuid.UUID, relative_path: Annotated[str, Form(max_length=2048)], file: Annotated[UploadFile, File()], service: Annotated[BatchService, Depends(get_batch_service)]):
    return BatchFileResponse.model_validate(service.upload(batch_id, relative_path, file))

@router.post("/{batch_id}/files/{file_id}/retry", response_model=BatchFileResponse)
def retry_batch_file(batch_id: uuid.UUID, file_id: uuid.UUID, service: Annotated[BatchService, Depends(get_batch_service)]):
    return BatchFileResponse.model_validate(service.retry(batch_id, file_id))

@router.post("/{batch_id}/files/{file_id}/ignore", response_model=BatchFileResponse)
def ignore_batch_file(batch_id: uuid.UUID, file_id: uuid.UUID, service: Annotated[BatchService, Depends(get_batch_service)]):
    return BatchFileResponse.model_validate(service.ignore(batch_id, file_id))

@router.post("/{batch_id}/cancel", response_model=BatchResponse)
def cancel_batch(batch_id: uuid.UUID, service: Annotated[BatchService, Depends(get_batch_service)]):
    return service.response(service.cancel(batch_id))
