"""知识库管理接口。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.knowledge_bases import KnowledgeBaseCreate, KnowledgeBaseListResponse, KnowledgeBaseResponse, KnowledgeBaseUpdate
from app.services.knowledge_bases import KnowledgeBaseService
from app.services.rbac import require_any_permission, require_permission


router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-bases"])

KNOWLEDGE_BASE_MANAGE = "KNOWLEDGE_BASE_MANAGE"


def get_service(session: Annotated[Session, Depends(get_session)]) -> KnowledgeBaseService:
    return KnowledgeBaseService(session)


def response(item, count: int = 0) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse(**{
        **KnowledgeBaseResponse.model_validate(item).model_dump(), "document_count": count,
    })


@router.get("", response_model=KnowledgeBaseListResponse)
def list_knowledge_bases(
    request: Request,
    service: Annotated[KnowledgeBaseService, Depends(get_service)],
):
    """有问答、检索或查看资料任一权限即可读取知识库基础列表。"""
    require_any_permission(
        getattr(request.state, "auth_user", None),
        ("ANSWER_USE", "SEARCH_USE", "DOCUMENT_VIEW", KNOWLEDGE_BASE_MANAGE),
    )
    values = service.list()
    return KnowledgeBaseListResponse(items=[response(item, count) for item, count in values], total=len(values))


@router.post("", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
def create_knowledge_base(
    body: KnowledgeBaseCreate,
    request: Request,
    service: Annotated[KnowledgeBaseService, Depends(get_service)],
):
    require_permission(getattr(request.state, "auth_user", None), KNOWLEDGE_BASE_MANAGE)
    return response(service.create(body.name, body.description, body.chunking_config))


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
def update_knowledge_base(
    knowledge_base_id: uuid.UUID,
    body: KnowledgeBaseUpdate,
    request: Request,
    service: Annotated[KnowledgeBaseService, Depends(get_service)],
):
    require_permission(getattr(request.state, "auth_user", None), KNOWLEDGE_BASE_MANAGE)
    return response(service.update(
        knowledge_base_id, body.name, body.description,
        body.chunking_config, "chunking_config" in body.model_fields_set,
    ))


@router.post("/{knowledge_base_id}/enable", response_model=KnowledgeBaseResponse)
def enable_knowledge_base(
    knowledge_base_id: uuid.UUID,
    request: Request,
    service: Annotated[KnowledgeBaseService, Depends(get_service)],
):
    require_permission(getattr(request.state, "auth_user", None), KNOWLEDGE_BASE_MANAGE)
    return response(service.set_enabled(knowledge_base_id, True))


@router.post("/{knowledge_base_id}/disable", response_model=KnowledgeBaseResponse)
def disable_knowledge_base(
    knowledge_base_id: uuid.UUID,
    request: Request,
    service: Annotated[KnowledgeBaseService, Depends(get_service)],
):
    require_permission(getattr(request.state, "auth_user", None), KNOWLEDGE_BASE_MANAGE)
    return response(service.set_enabled(knowledge_base_id, False))
