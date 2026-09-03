import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models.document import DocumentStatus
from app.schemas.documents import DocumentChunkResponse, DocumentContentResponse, DocumentFilters, DocumentListResponse, DocumentResponse
from app.services.documents import DocumentService
from app.services.managed_storage import ManagedStorage

router = APIRouter(prefix="/api/documents", tags=["documents"])


def get_document_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentService:
    return DocumentService(session, ManagedStorage(settings))


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: Annotated[UploadFile, File()],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentResponse:
    return DocumentResponse.model_validate(service.upload(file))


@router.get("", response_model=DocumentListResponse)
def list_documents(
    service: Annotated[DocumentService, Depends(get_document_service)],
    query: Annotated[str | None, Query(max_length=200)] = None,
    extension: Annotated[str | None, Query(max_length=16)] = None,
    document_status: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> DocumentListResponse:
    filters = DocumentFilters(query=query, extension=extension, status=document_status, page=page, page_size=page_size)
    documents, total = service.list(filters)
    return DocumentListResponse(items=[DocumentResponse.model_validate(item) for item in documents], page=page, page_size=page_size, total=total)


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: uuid.UUID,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentResponse:
    return DocumentResponse.model_validate(service.get(document_id))


@router.get("/{document_id}/content", response_model=DocumentContentResponse)
def get_document_content(
    document_id: uuid.UUID,
    service: Annotated[DocumentService, Depends(get_document_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> DocumentContentResponse:
    chunks, total = service.content(document_id, page, page_size)
    return DocumentContentResponse(
        items=[DocumentChunkResponse.model_validate(chunk) for chunk in chunks],
        page=page, page_size=page_size, total=total,
    )


@router.post("/{document_id}/reprocess", response_model=DocumentResponse)
def reprocess_document(
    document_id: uuid.UUID,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentResponse:
    return DocumentResponse.model_validate(service.reprocess(document_id))


@router.get("/{document_id}/download")
def download_document(
    document_id: uuid.UUID,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> FileResponse:
    document = service.get(document_id)
    return FileResponse(
        service.storage.resolve(document.stored_path),
        media_type=document.mime_type,
        filename=document.original_name,
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> Response:
    service.delete(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
