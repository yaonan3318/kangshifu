"""助手管理 API：创建、编辑、启停以及知识库绑定。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db import get_session
from app.errors import AppError
from app.models import (
    DEFAULT_ASSISTANT_ID, Assistant, Chatflow, ChatMessage, ChatMessageRole, ChatSession,
    KnowledgeBase, assistant_knowledge_bases,
)
from app.schemas.assistant import (
    AssistantKnowledgeBasesPut, AssistantListResponse, AssistantOut, AssistantUpsert,
    AssistantWelcomeResponse,
)
from app.api.auth import current_user
from app.services.audit import audit_action
from app.services.permissions import require_user
from app.services.rbac import require_permission

router = APIRouter(prefix="/api/assistants", tags=["assistants"])

ASSISTANT_MANAGE = "ASSISTANT_MANAGE"


def _meta(request: Request) -> dict:
    return {
        "ip_address": request.client.host if request.client else None,
        "request_id": request.headers.get("X-Request-ID"),
    }


def _assistant_payload(assistant: Assistant) -> AssistantOut:
    return AssistantOut(
        id=assistant.id, name=assistant.name, description=assistant.description,
        avatar=assistant.avatar, welcome_message=assistant.welcome_message,
        system_prompt=assistant.system_prompt, model_provider=assistant.model_provider,
        model_name=assistant.model_name, use_deepseek_allowed=assistant.use_deepseek_allowed,
        default_deepseek_enabled=assistant.default_deepseek_enabled,
        deepseek_enabled=assistant.deepseek_enabled, harness_enabled=assistant.harness_enabled,
        harness_context=assistant.harness_context, harness_namespace=assistant.harness_namespace,
        retrieval_limit=assistant.retrieval_limit, temperature=assistant.temperature,
        recommended_questions=list(assistant.recommended_questions or []),
        answer_template=assistant.answer_template, internet_enabled=assistant.internet_enabled,
        no_answer_policy=assistant.no_answer_policy,
        capabilities=list(assistant.capabilities or []), limitations=list(assistant.limitations or []),
        allow_all_knowledge_bases=assistant.allow_all_knowledge_bases,
        chatflow_id=assistant.chatflow_id,
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


def _validate_chatflow(session: Session, chatflow_id: uuid.UUID | None) -> None:
    if chatflow_id is not None and session.get(Chatflow, chatflow_id) is None:
        raise AppError("CHATFLOW_NOT_FOUND", "指定的流程不存在", 404)


def _apply(session: Session, assistant: Assistant, body: AssistantUpsert) -> Assistant:
    values = body.model_dump(exclude_unset=True)
    if values.get("chatflow_id") is not None:
        _validate_chatflow(session, values["chatflow_id"])
    for key, value in values.items():
        if key in ("recommended_questions", "capabilities", "limitations") and value is not None:
            value = [str(item).strip() for item in value if str(item).strip()]
        elif key == "harness_namespace":
            value = (value or "default").strip()
        elif key == "harness_context":
            value = value.strip() if value and value.strip() else None
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
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AssistantOut:
    """新建助手；未提供名称时用默认名称。"""
    admin = require_permission(current_user(request), ASSISTANT_MANAGE)
    name = (body.name or "").strip() or "未命名助手"
    with audit_action(
        session, "assistant_created", user=admin, target_type="assistant", **_meta(request),
    ) as audit:
        if session.scalar(select(Assistant).where(Assistant.name == name)) is not None:
            raise AppError("ASSISTANT_NAME_EXISTS", "已存在同名助手", 409)
        _validate_chatflow(session, body.chatflow_id)
        assistant = Assistant(
            name=name,
            chatflow_id=body.chatflow_id,
            description=body.description,
            avatar=body.avatar or "康",
            welcome_message=body.welcome_message,
            system_prompt=body.system_prompt,
            model_provider=body.model_provider or "ollama",
            model_name=body.model_name or None,
            use_deepseek_allowed=True if body.use_deepseek_allowed is None else body.use_deepseek_allowed,
            default_deepseek_enabled=False if body.default_deepseek_enabled is None else body.default_deepseek_enabled,
            deepseek_enabled=False if body.deepseek_enabled is None else body.deepseek_enabled,
            harness_enabled=False if body.harness_enabled is None else body.harness_enabled,
            harness_context=(body.harness_context or None),
            harness_namespace=(body.harness_namespace or "default").strip(),
            retrieval_limit=body.retrieval_limit or 6,
            temperature=0.2 if body.temperature is None else body.temperature,
            recommended_questions=[str(q) for q in (body.recommended_questions or [])],
            answer_template=body.answer_template or "AUTO",
            internet_enabled=bool(body.internet_enabled),
            no_answer_policy=body.no_answer_policy or "SUGGEST",
            capabilities=[str(item).strip() for item in (body.capabilities or []) if str(item).strip()],
            limitations=[str(item).strip() for item in (body.limitations or []) if str(item).strip()],
            allow_all_knowledge_bases=bool(body.allow_all_knowledge_bases),
            enabled=True if body.enabled is None else body.enabled,
        )
        session.add(assistant)
        session.commit()
        session.refresh(assistant)
        audit.id = assistant.id
        audit.detail = {"name": assistant.name}
    return _load(session, assistant.id)


@router.get("/{assistant_id}", response_model=AssistantOut)
def get_assistant(
    assistant_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
) -> AssistantOut:
    return _assistant_payload(_load(session, assistant_id))


@router.get("/{assistant_id}/welcome", response_model=AssistantWelcomeResponse)
def assistant_welcome(
    assistant_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AssistantWelcomeResponse:
    """助手欢迎页：能做什么/不能做什么、知识库范围、是否允许通用知识与运维、最近热门问题。"""
    user = require_user(current_user(request))
    assistant = _load(session, assistant_id)
    if assistant.allow_all_knowledge_bases:
        enabled = list(session.scalars(
            select(KnowledgeBase).where(KnowledgeBase.enabled.is_(True)).order_by(KnowledgeBase.name)
        ))
        bases = [{"id": str(kb.id), "name": kb.name} for kb in enabled]
        scope = "全部启用知识库"
        scope_configured = True
    elif assistant.knowledge_bases:
        bases = [{"id": str(kb.id), "name": kb.name} for kb in assistant.knowledge_bases]
        scope = "、".join(kb.name for kb in assistant.knowledge_bases)
        scope_configured = True
    else:
        # 专项助手未绑定知识库时不能默认放大到全部知识库。
        bases = []
        scope = "尚未配置资料范围"
        scope_configured = False
    recent = session.execute(
        select(ChatMessage.content)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .where(ChatSession.assistant_id == assistant_id, ChatMessage.role == ChatMessageRole.USER)
        .group_by(ChatMessage.content)
        .order_by(func.count(ChatMessage.id).desc(), func.max(ChatMessage.created_at).desc())
        .limit(5)
    ).all()
    return AssistantWelcomeResponse(
        id=assistant.id, name=assistant.name, avatar=assistant.avatar,
        description=assistant.description, welcome_message=assistant.welcome_message,
        capabilities=list(assistant.capabilities or []),
        limitations=list(assistant.limitations or []),
        recommended_questions=list(assistant.recommended_questions or []),
        recent_questions=[row[0] for row in recent if row[0]],
        knowledge_bases=bases, knowledge_scope=scope,
        knowledge_scope_configured=scope_configured,
        general_knowledge_allowed=bool(assistant.use_deepseek_allowed and assistant.deepseek_enabled),
        operations_allowed=bool(assistant.harness_enabled and user.is_super_admin),
        internet_enabled=assistant.internet_enabled,
        internet_configured=bool(get_settings().internet_search_enabled),
    )


@router.patch("/{assistant_id}", response_model=AssistantOut)
def update_assistant(
    assistant_id: uuid.UUID,
    body: AssistantUpsert,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AssistantOut:
    """更新助手字段；仅更新显式提供的字段。"""
    admin = require_permission(current_user(request), ASSISTANT_MANAGE)
    with audit_action(
        session, "assistant_updated", user=admin, target_type="assistant", target_id=assistant_id,
        detail={"fields": sorted(body.model_dump(exclude_unset=True).keys())}, **_meta(request),
    ):
        payload = _assistant_payload(_apply(session, _load(session, assistant_id), body))
    return payload


@router.post("/{assistant_id}/enable", response_model=AssistantOut)
def enable_assistant(
    assistant_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AssistantOut:
    admin = require_permission(current_user(request), ASSISTANT_MANAGE)
    with audit_action(
        session, "assistant_enabled", user=admin, target_type="assistant", target_id=assistant_id,
        **_meta(request),
    ):
        assistant = _load(session, assistant_id)
        assistant.enabled = True
        session.commit()
    return _assistant_payload(_load(session, assistant_id))


@router.post("/{assistant_id}/disable", response_model=AssistantOut)
def disable_assistant(
    assistant_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AssistantOut:
    admin = require_permission(current_user(request), ASSISTANT_MANAGE)
    with audit_action(
        session, "assistant_disabled", user=admin, target_type="assistant", target_id=assistant_id,
        **_meta(request),
    ):
        assistant = _load(session, assistant_id)
        assistant.enabled = False
        session.commit()
    return _assistant_payload(_load(session, assistant_id))


@router.put("/{assistant_id}/knowledge-bases", response_model=AssistantOut)
def set_assistant_knowledge_bases(
    assistant_id: uuid.UUID,
    body: AssistantKnowledgeBasesPut,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AssistantOut:
    """设置助手使用的知识库；传入空数组表示“全部启用知识库”。"""
    admin = require_permission(current_user(request), ASSISTANT_MANAGE)
    ids = list(dict.fromkeys(body.knowledge_base_ids))
    with audit_action(
        session, "assistant_knowledge_bases_changed", user=admin,
        target_type="assistant", target_id=assistant_id,
        detail={"knowledge_base_ids": [str(item) for item in ids]}, **_meta(request),
    ):
        _load(session, assistant_id)
        if ids:
            existing = set(session.scalars(select(KnowledgeBase.id).where(KnowledgeBase.id.in_(ids))).all())
            missing = [item for item in ids if item not in existing]
            if missing:
                raise AppError("KNOWLEDGE_BASE_NOT_FOUND", "指定的知识库不存在", 404, {"ids": [str(item) for item in missing]})
        session.execute(
            assistant_knowledge_bases.delete().where(assistant_knowledge_bases.c.assistant_id == assistant_id)
        )
        if ids:
            session.execute(
                assistant_knowledge_bases.insert(),
                [{"assistant_id": assistant_id, "knowledge_base_id": item} for item in ids],
            )
        session.commit()
    return _assistant_payload(_load(session, assistant_id))


@router.delete("/{assistant_id}")
def delete_assistant(
    assistant_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    """删除助手；默认助手不可删除。"""
    admin = require_permission(current_user(request), ASSISTANT_MANAGE)
    with audit_action(
        session, "assistant_deleted", user=admin, target_type="assistant", target_id=assistant_id,
        **_meta(request),
    ) as audit:
        if assistant_id == DEFAULT_ASSISTANT_ID:
            raise AppError("DEFAULT_ASSISTANT_PROTECTED", "默认助手不可删除", 400)
        assistant = _load(session, assistant_id)
        audit.detail = {"name": assistant.name}
        session.delete(assistant)
        session.commit()
    return {"deleted": True}
