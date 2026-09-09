"""文档上传、列表、详情、下载、重新处理和删除接口。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models.document import DocumentStatus
from app.schemas.documents import DocumentChunkResponse, DocumentContentResponse, DocumentDeleteRequest, DocumentFilters, DocumentListResponse, DocumentResponse, DocumentUpdateRequest
from app.services.documents import DocumentService
from app.services.managed_storage import ManagedStorage

router = APIRouter(prefix="/api/documents", tags=["documents"])


def get_document_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentService:
    """组合请求级数据库 Session 与磁盘存储，供路由函数注入使用。"""
    return DocumentService(session, ManagedStorage(settings))


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: Annotated[UploadFile, File()],
    service: Annotated[DocumentService, Depends(get_document_service)],
    knowledge_base_id: Annotated[uuid.UUID | None, Form()] = None,
) -> DocumentResponse:
    """上传一个文件；内容重复时返回 409，而不会重复占用磁盘。"""
    return document_response(service.upload(file, knowledge_base_id), service)


def document_response(document, service: DocumentService) -> DocumentResponse:
    data = {
        name: getattr(document, name)
        for name in DocumentResponse.model_fields
        if name not in {"tags", "chunk_count"}
    }
    data["tags"] = [tag.name for tag in document.tags]
    data["chunk_count"] = service.chunk_count(document.id)
    return DocumentResponse(**data)


@router.get("", response_model=DocumentListResponse)
def list_documents(
    service: Annotated[DocumentService, Depends(get_document_service)],
    query: Annotated[str | None, Query(max_length=200)] = None,
    extension: Annotated[str | None, Query(max_length=16)] = None,
    document_status: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    knowledge_base_id: uuid.UUID | None = None,
    tag: Annotated[str | None, Query(max_length=128)] = None,
    deleted: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> DocumentListResponse:
    """分页查询文档元数据，可按文件名、扩展名和处理状态过滤。"""
    filters = DocumentFilters(query=query, extension=extension, status=document_status, knowledge_base_id=knowledge_base_id, tag=tag, include_deleted=deleted, page=page, page_size=page_size)
    documents, total = service.list_documents(filters)
    return DocumentListResponse(items=[document_response(item, service) for item in documents], page=page, page_size=page_size, total=total)


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: uuid.UUID,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentResponse:
    """取得单个文档的元数据与当前处理状态。"""
    return document_response(service.get(document_id), service)


@router.patch("/{document_id}", response_model=DocumentResponse)
def update_document(document_id: uuid.UUID, body: DocumentUpdateRequest, service: Annotated[DocumentService, Depends(get_document_service)]):
    return document_response(service.update(document_id, body), service)


@router.post("/{document_id}/enable", response_model=DocumentResponse)
def enable_document(document_id: uuid.UUID, service: Annotated[DocumentService, Depends(get_document_service)]):
    return document_response(service.set_enabled(document_id, True), service)


@router.post("/{document_id}/disable", response_model=DocumentResponse)
def disable_document(document_id: uuid.UUID, service: Annotated[DocumentService, Depends(get_document_service)]):
    return document_response(service.set_enabled(document_id, False), service)


@router.post("/{document_id}/restore", response_model=DocumentResponse)
def restore_document(document_id: uuid.UUID, service: Annotated[DocumentService, Depends(get_document_service)]):
    return document_response(service.restore(document_id), service)


@router.get("/{document_id}/versions", response_model=list[DocumentResponse])
def document_versions(document_id: uuid.UUID, service: Annotated[DocumentService, Depends(get_document_service)]):
    return [document_response(item, service) for item in service.versions(document_id)]


@router.get("/{document_id}/content", response_model=DocumentContentResponse)
def get_document_content(
    document_id: uuid.UUID,
    service: Annotated[DocumentService, Depends(get_document_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> DocumentContentResponse:
    """分页读取文档解析后的文本片段，不会再次打开原始附件。"""
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
    """清除旧片段并重新排队解析，适用于修复 OCR/解析配置后重试。"""
    return document_response(service.reprocess(document_id), service)


@router.get("/{document_id}/download")
def download_document(
    document_id: uuid.UUID,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> FileResponse:
    """从受管磁盘目录下载原始附件。"""
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
    body: DocumentDeleteRequest | None = None,
) -> Response:
    """将文档移入回收站；附件和索引继续保留以便恢复。"""
    service.delete(document_id, body.reason if body else None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{document_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge_document(document_id: uuid.UUID, service: Annotated[DocumentService, Depends(get_document_service)]) -> Response:
    """永久删除回收站中的文档及原始附件。"""
    service.purge(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
