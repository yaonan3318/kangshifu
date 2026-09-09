"""文档片段查看、编辑、启停和重建接口。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.schemas.chunks import ChunkListResponse, ChunkResponse, ChunkUpdateRequest
from app.services.chunks import ChunkService


router = APIRouter(prefix="/api", tags=["chunks"])


def get_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChunkService:
    return ChunkService(session, settings)


@router.get("/documents/{document_id}/chunks", response_model=ChunkListResponse)
def list_chunks(document_id: uuid.UUID, service: Annotated[ChunkService, Depends(get_service)], page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 25):
    items, total = service.list_chunks(document_id, page, page_size)
    return ChunkListResponse(items=[ChunkResponse.model_validate(item) for item in items], page=page, page_size=page_size, total=total)


@router.patch("/chunks/{chunk_id}", response_model=ChunkResponse)
def update_chunk(chunk_id: uuid.UUID, body: ChunkUpdateRequest, service: Annotated[ChunkService, Depends(get_service)]):
    return ChunkResponse.model_validate(service.update_content(chunk_id, body.content))


@router.post("/chunks/{chunk_id}/enable", response_model=ChunkResponse)
def enable_chunk(chunk_id: uuid.UUID, service: Annotated[ChunkService, Depends(get_service)]):
    return ChunkResponse.model_validate(service.set_enabled(chunk_id, True))


@router.post("/chunks/{chunk_id}/disable", response_model=ChunkResponse)
def disable_chunk(chunk_id: uuid.UUID, service: Annotated[ChunkService, Depends(get_service)]):
    return ChunkResponse.model_validate(service.set_enabled(chunk_id, False))


@router.post("/chunks/{chunk_id}/reindex", response_model=ChunkResponse)
def reindex_chunk(chunk_id: uuid.UUID, service: Annotated[ChunkService, Depends(get_service)]):
    return ChunkResponse.model_validate(service.reindex(chunk_id))


@router.post("/chunks/{chunk_id}/restore-original", response_model=ChunkResponse)
def restore_chunk(chunk_id: uuid.UUID, service: Annotated[ChunkService, Depends(get_service)]):
    return ChunkResponse.model_validate(service.restore_original(chunk_id))
