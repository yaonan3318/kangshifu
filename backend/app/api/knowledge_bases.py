"""知识库管理接口。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.knowledge_bases import KnowledgeBaseCreate, KnowledgeBaseListResponse, KnowledgeBaseResponse, KnowledgeBaseUpdate
from app.services.knowledge_bases import KnowledgeBaseService


router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-bases"])


def get_service(session: Annotated[Session, Depends(get_session)]) -> KnowledgeBaseService:
    return KnowledgeBaseService(session)


def response(item, count: int = 0) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse(**{
        **KnowledgeBaseResponse.model_validate(item).model_dump(), "document_count": count,
    })


@router.get("", response_model=KnowledgeBaseListResponse)
def list_knowledge_bases(service: Annotated[KnowledgeBaseService, Depends(get_service)]):
    values = service.list()
    return KnowledgeBaseListResponse(items=[response(item, count) for item, count in values], total=len(values))


@router.post("", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
def create_knowledge_base(body: KnowledgeBaseCreate, service: Annotated[KnowledgeBaseService, Depends(get_service)]):
    return response(service.create(body.name, body.description))


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
def update_knowledge_base(knowledge_base_id: uuid.UUID, body: KnowledgeBaseUpdate, service: Annotated[KnowledgeBaseService, Depends(get_service)]):
    return response(service.update(knowledge_base_id, body.name, body.description))


@router.post("/{knowledge_base_id}/enable", response_model=KnowledgeBaseResponse)
def enable_knowledge_base(knowledge_base_id: uuid.UUID, service: Annotated[KnowledgeBaseService, Depends(get_service)]):
    return response(service.set_enabled(knowledge_base_id, True))


@router.post("/{knowledge_base_id}/disable", response_model=KnowledgeBaseResponse)
def disable_knowledge_base(knowledge_base_id: uuid.UUID, service: Annotated[KnowledgeBaseService, Depends(get_service)]):
    return response(service.set_enabled(knowledge_base_id, False))
