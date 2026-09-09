"""助手管理 API：创建、编辑、启停以及知识库绑定。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_session
from app.errors import AppError
from app.models import DEFAULT_ASSISTANT_ID, Assistant, KnowledgeBase, assistant_knowledge_bases
from app.schemas.assistant import (
    AssistantKnowledgeBasesPut, AssistantListResponse, AssistantOut, AssistantUpsert,
)

router = APIRouter(prefix="/api/assistants", tags=["assistants"])


def _assistant_payload(assistant: Assistant) -> AssistantOut:
    return AssistantOut(
        id=assistant.id, name=assistant.name, description=assistant.description,
        avatar=assistant.avatar, welcome_message=assistant.welcome_message,
        system_prompt=assistant.system_prompt, model_provider=assistant.model_provider,
        model_name=assistant.model_name, use_deepseek_allowed=assistant.use_deepseek_allowed,
        default_deepseek_enabled=assistant.default_deepseek_enabled,
        retrieval_limit=assistant.retrieval_limit, temperature=assistant.temperature,
        recommended_questions=list(assistant.recommended_questions or []),
        enabled=assistant.enabled, created_at=assistant.created_at, updated_at=assistant.updated_at,
        knowledge_base_ids=[kb.id for kb in assistant.knowledge_bases],
    )


def _load(session: Session, assistant_id: uuid.UUID) -> Assistant:
    assistant = session.scalar(
        select(Assistant).where(Assistant.id == assistant_id).options(selectinload(Assistant.knowledge_bases))
    )
    if assistant is None:
        raise AppError("ASSISTANT_NOT_FOUND", "助手不存在", 404)
    return assistant


def _apply(session: Session, assistant: Assistant, body: AssistantUpsert) -> Assistant:
    values = body.model_dump(exclude_unset=True)
    for key, value in values.items():
        if key == "recommended_questions" and value is not None:
            value = [str(item).strip() for item in value if str(item).strip()]
        if key != "name" or (value and value.strip()):
            setattr(assistant, key, value)
    if "name" in values and values["name"] is not None:
        assistant.name = values["name"].strip()
    session.add(assistant)
    session.commit()
    session.refresh(assistant)
    return _load(session, assistant.id)


@router.get("", response_model=AssistantListResponse)
def list_assistants(
    session: Annotated[Session, Depends(get_session)],
    enabled: bool | None = None,
) -> AssistantListResponse:
    """列出助手；enabled=true 只返回启用中的助手。"""
    statement = select(Assistant).options(selectinload(Assistant.knowledge_bases))
    if enabled is not None:
        statement = statement.where(Assistant.enabled.is_(enabled))
    rows = session.scalars(statement.order_by(Assistant.created_at.asc())).all()
    return AssistantListResponse(items=[_assistant_payload(item) for item in rows], total=len(rows))


@router.post("", response_model=AssistantOut)
def create_assistant(
    body: AssistantUpsert,
    session: Annotated[Session, Depends(get_session)],
) -> AssistantOut:
    """新建助手；未提供名称时用默认名称。"""
    name = (body.name or "").strip() or "未命名助手"
    if session.scalar(select(Assistant).where(Assistant.name == name)) is not None:
        raise AppError("ASSISTANT_NAME_EXISTS", "已存在同名助手", 409)
    assistant = Assistant(
        name=name,
        description=body.description,
        avatar=body.avatar or "康",
        welcome_message=body.welcome_message,
        system_prompt=body.system_prompt,
        model_provider=body.model_provider or "ollama",
        model_name=body.model_name or None,
        use_deepseek_allowed=True if body.use_deepseek_allowed is None else body.use_deepseek_allowed,
        default_deepseek_enabled=False if body.default_deepseek_enabled is None else body.default_deepseek_enabled,
        retrieval_limit=body.retrieval_limit or 6,
        temperature=0.2 if body.temperature is None else body.temperature,
        recommended_questions=[str(q) for q in (body.recommended_questions or [])],
        enabled=True if body.enabled is None else body.enabled,
    )
    session.add(assistant)
    session.commit()
    session.refresh(assistant)
    return _load(session, assistant.id)


@router.get("/{assistant_id}", response_model=AssistantOut)
def get_assistant(
    assistant_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
) -> AssistantOut:
    return _assistant_payload(_load(session, assistant_id))


@router.patch("/{assistant_id}", response_model=AssistantOut)
def update_assistant(
    assistant_id: uuid.UUID,
    body: AssistantUpsert,
    session: Annotated[Session, Depends(get_session)],
) -> AssistantOut:
    """更新助手字段；仅更新显式提供的字段。"""
    return _assistant_payload(_apply(session, _load(session, assistant_id), body))


@router.post("/{assistant_id}/enable", response_model=AssistantOut)
def enable_assistant(
    assistant_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
) -> AssistantOut:
    assistant = _load(session, assistant_id)
    assistant.enabled = True
    session.commit()
    return _assistant_payload(_load(session, assistant_id))


@router.post("/{assistant_id}/disable", response_model=AssistantOut)
def disable_assistant(
    assistant_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
) -> AssistantOut:
    assistant = _load(session, assistant_id)
    assistant.enabled = False
    session.commit()
    return _assistant_payload(_load(session, assistant_id))


@router.put("/{assistant_id}/knowledge-bases", response_model=AssistantOut)
def set_assistant_knowledge_bases(
    assistant_id: uuid.UUID,
    body: AssistantKnowledgeBasesPut,
    session: Annotated[Session, Depends(get_session)],
) -> AssistantOut:
    """设置助手使用的知识库；传入空数组表示“全部启用知识库”。"""
    assistant = _load(session, assistant_id)
    ids = list(dict.fromkeys(body.knowledge_base_ids))
    if ids:
        existing = set(session.scalars(select(KnowledgeBase.id).where(KnowledgeBase.id.in_(ids))).all())
        missing = [item for item in ids if item not in existing]
        if missing:
            raise AppError("KNOWLEDGE_BASE_NOT_FOUND", "指定的知识库不存在", 404, {"ids": [str(item) for item in missing]})
        session.execute(
            assistant_knowledge_bases.delete().where(assistant_knowledge_bases.c.assistant_id == assistant_id)
        )
        session.execute(
            assistant_knowledge_bases.insert(),
            [{"assistant_id": assistant_id, "knowledge_base_id": item} for item in ids],
        )
    else:
        session.execute(
            assistant_knowledge_bases.delete().where(assistant_knowledge_bases.c.assistant_id == assistant_id)
        )
    session.commit()
    return _assistant_payload(_load(session, assistant_id))


@router.delete("/{assistant_id}")
def delete_assistant(
    assistant_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    """删除助手；默认助手不可删除。"""
    if assistant_id == DEFAULT_ASSISTANT_ID:
        raise AppError("DEFAULT_ASSISTANT_PROTECTED", "默认助手不可删除", 400)
    assistant = _load(session, assistant_id)
    session.delete(assistant)
    session.commit()
    return {"deleted": True}
