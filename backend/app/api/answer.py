"""RAG 问答接口，以 Server-Sent Events (SSE) 持续推送生成结果。

每次问答会把用户问题和最终助手回答（含引用快照）写入数据库，切换页面或重启
服务后仍可打开历史会话。助手回答先以 GENERATING 状态落库，结束时统一更新。
"""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.errors import AppError
from app.models.chat import ChatProvider
from app.models.assistant import Assistant
from app.schemas.answer import AnswerEvent, AnswerRequest, AnswerStatusResponse
from app.services.chat import AnswerRecorder, ChatService
from app.services.audit import record as audit_record
from app.services.harness import HarnessService
from app.services.knowledge_gaps import record_gap
from app.services.permissions import require_user
from app.services.rag import RagService
from app.services.rbac import require_permission
from app.services.retrieval_config import load_active_config

router = APIRouter(prefix="/api/answer", tags=["answer"])

ANSWER_USE = "ANSWER_USE"
logger = logging.getLogger(__name__)


def get_rag_service(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RagService:
    """为当前请求创建 RAG 编排服务，并复用请求级数据库 Session。

    使用默认检索配置版本（含 Query Rewrite / Multi-query / Reranker 设置），
    使管理页面保存的配置对问答立即生效。
    """
    config = load_active_config(session, settings)
    return RagService(session, settings, user=getattr(request.state, "auth_user", None), config=config)


def encode_sse(event: AnswerEvent) -> str:
    """把 Pydantic 事件编码成浏览器 EventSource/fetch 可读取的 SSE 帧。"""
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


def _provider_value(event: AnswerEvent) -> ChatProvider:
    if event.provider is None:
        return ChatProvider.LOCAL
    return ChatProvider(str(event.provider.value))


def apply_assistant_runtime_policy(
    session: Session, body: AnswerRequest, chat_user: object | None,
) -> AnswerRequest:
    """用服务端助手配置覆盖客户端能力开关，避免用户绕过管理员策略。"""
    assistant = session.get(Assistant, body.assistant_id) if body.assistant_id else None
    available = assistant is not None and assistant.enabled
    harness_enabled = bool(
        available and assistant.harness_enabled
        and assistant.harness_context
        and getattr(chat_user, "is_super_admin", False)
    )
    return body.model_copy(update={
        "use_deepseek": bool(available and assistant.deepseek_enabled),
        "use_harness": harness_enabled,
        "k8s_context": assistant.harness_context if harness_enabled else None,
        "k8s_namespace": assistant.harness_namespace if harness_enabled else None,
        "deployment_yaml": None,
    })


@router.get("/status", response_model=AnswerStatusResponse)
async def answer_status(request: Request, service: Annotated[RagService, Depends(get_rag_service)]) -> AnswerStatusResponse:
    """检查本地 Ollama 模型是否就绪以及 DeepSeek 是否已配置；登录后可访问。"""
    require_user(getattr(request.state, "auth_user", None))
    return await service.status()


@router.post("/warmup")
async def answer_warmup(request: Request, service: Annotated[RagService, Depends(get_rag_service)]) -> dict:
    """预热本地模型：把模型加载进驻留内存，显著加快首次问答。"""
    require_permission(getattr(request.state, "auth_user", None), ANSWER_USE)
    warmed = await service.ollama.warmup()
    return {"warmed": warmed, "message": "本地模型已预热" if warmed else "预热失败，请检查 Ollama"}


@router.post("/stream")
async def answer_stream(
    body: AnswerRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[RagService, Depends(get_rag_service)],
) -> StreamingResponse:
    """先检索内部资料，再流式返回千问答案，并按需用 DeepSeek 替换增强答案。

    会话由前端传入 session_id；未传入时自动新建会话并把首问作为标题。
    """
    # 提前校验会话存在（归档会话也可继续提问），避免进入流式阶段后才发现 404。
    chat_user = require_permission(getattr(request.state, "auth_user", None), ANSWER_USE)
    body = apply_assistant_runtime_policy(session, body, chat_user)
    # Harness 可执行运维工具，权限闭环前仅限管理员使用，避免绕过文档权限。
    if body.use_harness and (chat_user is None or not chat_user.is_super_admin):
        raise AppError("HARNESS_FORBIDDEN", "Harness 功能仅限管理员使用", 403)
    ip_address = request.client.host if request.client else None
    request_id = request.headers.get("X-Request-ID")
    chat = ChatService(session, user=chat_user)
    if body.session_id is not None:
        try:
            chat.get(body.session_id, include_archived=True)
        except KeyError as exc:
            raise AppError("CHAT_SESSION_NOT_FOUND", "会话不存在", 404) from exc

    recorder = AnswerRecorder(session, user=chat_user)
    if body.regenerate_message_id is not None:
        try:
            prepared = recorder.begin_regenerate(body.regenerate_message_id)
        except KeyError as exc:
            raise AppError("CHAT_MESSAGE_NOT_FOUND", "待重新生成的回答不存在", 404) from exc
    else:
        prepared = recorder.prepare(body.question, body.session_id, assistant_id=body.assistant_id)

    async def events():
        is_harness = body.use_harness
        text_parts: list[str] = []
        sources: list = []
        metrics_payload: dict | None = None
        finalized = False
        disconnected = False
        stream = (
            HarnessService(service.search_service.session, service.settings, user=chat_user).start(body)
            if is_harness
            else service.stream(body)
        )
        try:
            while True:
                try:
                    event = await stream.__anext__()
                except StopAsyncIteration:
                    break
                # 客户端关闭页面后尽快停止生成，避免模型继续占用计算资源。
                if await request.is_disconnected():
                    disconnected = True
                    break
                if event.type == "sources" and event.sources is not None:
                    sources = event.sources
                elif event.type == "metrics" and event.metrics is not None:
                    metrics_payload = event.metrics
                elif event.type == "replace":
                    text_parts.clear()
                elif event.type == "delta" and event.text:
                    text_parts.append(event.text)
                elif event.type == "stage" and event.stage == "deepseek_enhancing":
                    audit_record(
                        session, "external_llm_requested", user=chat_user,
                        target_type="chat_session", target_id=prepared.id,
                        detail={"document_ids": [str(item.document_id) for item in sources]},
                        ip_address=ip_address, request_id=request_id,
                    )
                elif event.type == "warning" and event.warning is not None:
                    if event.warning.code in ("ASSISTANT_DEEPSEEK_BLOCKED", "EXTERNAL_LLM_BLOCKED", "DEEPSEEK_NOT_CONFIGURED"):
                        audit_record(
                            session, "external_llm_blocked", user=chat_user,
                            target_type="chat_session", target_id=prepared.id,
                            detail={"reason": event.warning.code, "message": event.warning.message},
                            ip_address=ip_address, request_id=request_id,
                        )
                    elif event.warning.code.startswith("DEEPSEEK_"):
                        audit_record(
                            session, "external_llm_failed", user=chat_user,
                            target_type="chat_session", target_id=prepared.id,
                            detail={"error_code": event.warning.code, "message": event.warning.message},
                            ip_address=ip_address, success=False, error_code=event.warning.code,
                            request_id=request_id,
                        )
                elif event.type == "done":
                    content = "".join(text_parts)
                    provider = _provider_value(event)
                    recorder.complete(
                        content,
                        provider,
                        event.scope.value if event.scope is not None else None,
                        sources,
                        metrics=metrics_payload,
                    )
                    if provider == ChatProvider.DEEPSEEK:
                        audit_record(
                            session, "external_llm_succeeded", user=chat_user,
                            target_type="chat_session", target_id=prepared.id,
                            detail={
                                "scope": event.scope.value if event.scope is not None else None,
                                "provider": "DEEPSEEK",
                                "document_ids": [str(item.document_id) for item in sources],
                            },
                            ip_address=ip_address, request_id=request_id,
                        )
                    finalized = True
                elif event.type == "no_answer" and event.no_answer:
                    # P2-5：无答案/低置信度自动进入知识缺口中心。
                    reason_map = {
                        "NO_RELEVANT_DOCUMENT": "NO_ANSWER",
                        "LOW_RELEVANCE": "LOW_CONFIDENCE",
                        "PERMISSION_RESTRICTED": "PERMISSION_RESTRICTED",
                    }
                    mapped = reason_map.get(event.no_answer.get("reason"))
                    if mapped:
                        record_gap(
                            session, body.question, mapped,
                            message_id=recorder.assistant.id if recorder.assistant else None,
                            answer="".join(text_parts),
                        )
                elif event.type == "harness_done":
                    content = "".join(text_parts)
                    recorder.complete(content, ChatProvider.HARNESS, "INTERNAL", sources, metrics=metrics_payload)
                    finalized = True
                elif event.type == "error" and event.error:
                    error_code = event.error.get("code", "ANSWER_FAILED")
                    recorder.mark_failed(
                        "".join(text_parts), error_code,
                        event.error.get("message", "问答处理失败"),
                    )
                    audit_record(
                        session, "answer_failed", user=chat_user,
                        target_type="chat_session", target_id=prepared.id,
                        detail={"error_code": error_code},
                        ip_address=ip_address, success=False, error_code=error_code,
                        request_id=request_id,
                    )
                    finalized = True
                yield encode_sse(event)
        except asyncio.CancelledError:
            # 客户端断开或关闭页面会触发取消；把未完成消息标记为已停止。
            if not finalized:
                recorder.mark_stopped("".join(text_parts))
                finalized = True
            raise
        finally:
            if not finalized:
                recorder.mark_stopped("".join(text_parts))
            if disconnected or not finalized:
                try:
                    await stream.aclose()
                except (RuntimeError, asyncio.CancelledError):
                    pass

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Chat-Session-Id": str(prepared.id),
            "X-Chat-Message-Id": str(recorder.assistant.id) if recorder.assistant else "",
        },
    )
