"""轻量 Chatflow API：流程草稿、发布版本、回滚、调试运行与助手绑定（ASSISTANT_MANAGE）。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.db import get_session
from app.models import Assistant, Chatflow
from app.schemas.chatflow import (
    ChatflowCreate, ChatflowDebugRequest, ChatflowDebugResponse, ChatflowListResponse, ChatflowOut,
    ChatflowPublishRequest, ChatflowRollbackRequest, ChatflowUpdate, ChatflowVersionOut,
    NodeTypeListResponse, NodeTypeOut,
)
from app.services.chatflow import ChatflowEngine, ChatflowService, NODE_TYPES
from app.services.rbac import require_permission

router = APIRouter(prefix="/api/chatflows", tags=["chatflows"])

ASSISTANT_MANAGE = "ASSISTANT_MANAGE"


def get_service(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> ChatflowService:
    require_permission(current_user(request), ASSISTANT_MANAGE)
    return ChatflowService(session)


def _payload(session: Session, chatflow: Chatflow) -> ChatflowOut:
    count = session.scalar(
        select(func.count()).select_from(Assistant).where(Assistant.chatflow_id == chatflow.id)
    ) or 0
    data = ChatflowOut.model_validate(chatflow)
    data.bound_assistant_count = count
    return data


@router.get("/node-types", response_model=NodeTypeListResponse)
def list_node_types(request: Request):
    require_permission(current_user(request), ASSISTANT_MANAGE)
    return NodeTypeListResponse(items=[NodeTypeOut(**item) for item in NODE_TYPES], total=len(NODE_TYPES))


@router.get("", response_model=ChatflowListResponse)
def list_chatflows(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    require_permission(current_user(request), ASSISTANT_MANAGE)
    items = ChatflowService(session).list()
    return ChatflowListResponse(items=[_payload(session, item) for item in items], total=len(items))


@router.post("", response_model=ChatflowOut, status_code=status.HTTP_201_CREATED)
def create_chatflow(
    body: ChatflowCreate,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    require_permission(current_user(request), ASSISTANT_MANAGE)
    value = ChatflowService(session).create(body.name, body.description, body.graph)
    return _payload(session, value)


@router.get("/{chatflow_id}", response_model=ChatflowOut)
def get_chatflow(
    chatflow_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    require_permission(current_user(request), ASSISTANT_MANAGE)
    return _payload(session, ChatflowService(session).get(chatflow_id))


@router.patch("/{chatflow_id}", response_model=ChatflowOut)
def update_chatflow(
    chatflow_id: uuid.UUID,
    body: ChatflowUpdate,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    require_permission(current_user(request), ASSISTANT_MANAGE)
    value = ChatflowService(session).update(
        chatflow_id, name=body.name, description=body.description,
        graph=body.graph, enabled=body.enabled, description_set="description" in body.model_fields_set,
    )
    return _payload(session, value)


@router.delete("/{chatflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chatflow(
    chatflow_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    require_permission(current_user(request), ASSISTANT_MANAGE)
    ChatflowService(session).delete(chatflow_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{chatflow_id}/publish", response_model=ChatflowVersionOut)
def publish_chatflow(
    chatflow_id: uuid.UUID,
    body: ChatflowPublishRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    require_permission(current_user(request), ASSISTANT_MANAGE)
    return ChatflowVersionOut.model_validate(ChatflowService(session).publish(chatflow_id, body.note))


@router.post("/{chatflow_id}/rollback", response_model=ChatflowOut)
def rollback_chatflow(
    chatflow_id: uuid.UUID,
    body: ChatflowRollbackRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    require_permission(current_user(request), ASSISTANT_MANAGE)
    value = ChatflowService(session).rollback(chatflow_id, body.version)
    return _payload(session, value)


@router.get("/{chatflow_id}/versions", response_model=list[ChatflowVersionOut])
def list_versions(
    chatflow_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    require_permission(current_user(request), ASSISTANT_MANAGE)
    return [ChatflowVersionOut.model_validate(item) for item in ChatflowService(session).list_versions(chatflow_id)]


@router.get("/{chatflow_id}/versions/{version}", response_model=ChatflowVersionOut)
def get_version(
    chatflow_id: uuid.UUID,
    version: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    require_permission(current_user(request), ASSISTANT_MANAGE)
    return ChatflowVersionOut.model_validate(ChatflowService(session).get_version(chatflow_id, version))


@router.post("/{chatflow_id}/debug", response_model=ChatflowDebugResponse)
async def debug_chatflow(
    chatflow_id: uuid.UUID,
    body: ChatflowDebugRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    require_permission(current_user(request), ASSISTANT_MANAGE)
    service = ChatflowService(session)
    chatflow = service.get(chatflow_id)
    engine = ChatflowEngine(session, request.app.state.settings, user=current_user(request))
    result = await engine.debug_run(
        chatflow.draft_graph, body.question, body.knowledge_base_id, body.include_generation,
    )
    return ChatflowDebugResponse(**result)
