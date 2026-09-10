"""文档片段查看、编辑、启停和重建接口。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.schemas.chunks import ChunkListResponse, ChunkResponse, ChunkUpdateRequest
from app.services.audit import audit_action
from app.services.chunks import ChunkService


router = APIRouter(prefix="/api", tags=["chunks"])


def get_service(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChunkService:
    return ChunkService(session, settings, user=current_user(request))


def _meta(request: Request) -> dict:
    return {
        "ip_address": request.client.host if request.client else None,
        "request_id": request.headers.get("X-Request-ID"),
    }


@router.get("/documents/{document_id}/chunks", response_model=ChunkListResponse)
def list_chunks(document_id: uuid.UUID, service: Annotated[ChunkService, Depends(get_service)], page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 25):
    items, total = service.list_chunks(document_id, page, page_size)
    return ChunkListResponse(items=[ChunkResponse.model_validate(item) for item in items], page=page, page_size=page_size, total=total)


@router.patch("/chunks/{chunk_id}", response_model=ChunkResponse)
def update_chunk(chunk_id: uuid.UUID, body: ChunkUpdateRequest, request: Request, service: Annotated[ChunkService, Depends(get_service)]):
    with audit_action(
        service.session, "chunk_updated", user=current_user(request),
        target_type="document_chunk", target_id=chunk_id, **_meta(request),
    ) as audit:
        chunk = service.update_content(chunk_id, body.content)
        audit.detail = {"document_id": str(chunk.document_id)}
    return ChunkResponse.model_validate(chunk)


@router.post("/chunks/{chunk_id}/enable", response_model=ChunkResponse)
def enable_chunk(chunk_id: uuid.UUID, request: Request, service: Annotated[ChunkService, Depends(get_service)]):
    with audit_action(
        service.session, "chunk_updated", user=current_user(request),
        target_type="document_chunk", target_id=chunk_id, **_meta(request),
    ) as audit:
        chunk = service.set_enabled(chunk_id, True)
        audit.detail = {"document_id": str(chunk.document_id), "enabled": True}
    return ChunkResponse.model_validate(chunk)


@router.post("/chunks/{chunk_id}/disable", response_model=ChunkResponse)
def disable_chunk(chunk_id: uuid.UUID, request: Request, service: Annotated[ChunkService, Depends(get_service)]):
    with audit_action(
        service.session, "chunk_updated", user=current_user(request),
        target_type="document_chunk", target_id=chunk_id, **_meta(request),
    ) as audit:
        chunk = service.set_enabled(chunk_id, False)
        audit.detail = {"document_id": str(chunk.document_id), "enabled": False}
    return ChunkResponse.model_validate(chunk)


@router.post("/chunks/{chunk_id}/reindex", response_model=ChunkResponse)
def reindex_chunk(chunk_id: uuid.UUID, request: Request, service: Annotated[ChunkService, Depends(get_service)]):
    with audit_action(
        service.session, "chunk_updated", user=current_user(request),
        target_type="document_chunk", target_id=chunk_id, **_meta(request),
    ) as audit:
        chunk = service.reindex(chunk_id)
        audit.detail = {"document_id": str(chunk.document_id), "reindexed": True}
    return ChunkResponse.model_validate(chunk)


@router.post("/chunks/{chunk_id}/restore-original", response_model=ChunkResponse)
def restore_chunk(chunk_id: uuid.UUID, request: Request, service: Annotated[ChunkService, Depends(get_service)]):
    with audit_action(
        service.session, "chunk_updated", user=current_user(request),
        target_type="document_chunk", target_id=chunk_id, **_meta(request),
    ) as audit:
        chunk = service.restore_original(chunk_id)
        audit.detail = {"document_id": str(chunk.document_id), "restored": True}
    return ChunkResponse.model_validate(chunk)
