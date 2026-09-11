"""RAG 问答接口，以 Server-Sent Events (SSE) 持续推送生成结果。

P2-5：一次问答会创建一个持久化 Answer Job，生成在后台任务中进行，不依赖浏览器连接。
SSE 只订阅任务广播；页面刷新或断网后可按游标续传，只有用户显式停止才会取消任务。
"""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import SessionLocal, get_session
from app.errors import AppError
from app.models import AnswerJob, AnswerJobStatus, TERMINAL_STATUSES
from app.models.chat import ChatProvider
from app.models.assistant import Assistant
from app.schemas.answer import (
    AnswerEvent, AnswerJobOut, AnswerProvider, AnswerRequest, AnswerSource, AnswerStatusResponse,
    KnowledgeScope,
)
from app.services.answer_jobs import RUNNING_TASKS, AnswerJobService, get_hub
from app.services.answer_runner import run_answer_job
from app.services.chat import AnswerRecorder, ChatService
from app.services.audit import record as audit_record
from app.services.harness import HarnessService
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
    """为当前请求创建 RAG 编排服务，并复用请求级数据库 Session。"""
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
        "use_deepseek": bool(
            available and assistant.deepseek_enabled and assistant.use_deepseek_allowed
        ),
        "use_harness": harness_enabled,
        "k8s_context": assistant.harness_context if harness_enabled else None,
        "k8s_namespace": assistant.harness_namespace if harness_enabled else None,
        "deployment_yaml": None,
    })


def _job_out(job: AnswerJob) -> AnswerJobOut:
    return AnswerJobOut(
        id=job.id, conversation_id=job.conversation_id, message_id=job.message_id,
        status=job.status.value if hasattr(job.status, "value") else str(job.status),
        current_stage=job.current_stage, partial_content=job.partial_content or "",
        event_cursor=job.event_cursor or 0, metrics=dict(job.metrics or {}),
        error_code=job.error_code, error_message=job.error_message,
        created_at=job.created_at, started_at=job.started_at,
        completed_at=job.completed_at, cancelled_at=job.cancelled_at,
    )


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


def _terminal_events(job: AnswerJob, sources_payload: list[dict]) -> list[AnswerEvent]:
    """任务已结束时，用持久化状态重建收尾事件，供刷新/重连恢复。"""
    metrics = dict(job.metrics or {})
    events: list[AnswerEvent] = []
    if metrics.get("citation_check"):
        events.append(AnswerEvent(type="citation_check", citation_check=metrics["citation_check"]))
    if metrics.get("no_answer"):
        events.append(AnswerEvent(type="no_answer", no_answer=metrics["no_answer"]))
    if metrics.get("confidence"):
        events.append(AnswerEvent(
            type="confidence", confidence=metrics["confidence"], question_type=metrics.get("question_type"),
        ))
    if metrics.get("suggestions"):
        events.append(AnswerEvent(type="suggestions", suggestions=metrics["suggestions"]))
    status = job.status.value if hasattr(job.status, "value") else str(job.status)
    if status == AnswerJobStatus.FAILED.value:
        events.append(AnswerEvent(type="error", error={
            "code": job.error_code or "ANSWER_FAILED",
            "message": job.error_message or "问答处理失败",
        }))
    elif status == AnswerJobStatus.COMPLETED.value:
        try:
            provider = AnswerProvider(metrics.get("provider") or "LOCAL")
        except ValueError:
            provider = AnswerProvider.LOCAL
        try:
            scope = KnowledgeScope(metrics["scope"]) if metrics.get("scope") else KnowledgeScope.NONE
        except ValueError:
            scope = KnowledgeScope.NONE
        events.append(AnswerEvent(type="metrics", metrics=metrics.get("metrics") or {}))
        events.append(AnswerEvent(
            type="done", provider=provider, scope=scope,
            source_count=len(sources_payload), question_type=metrics.get("question_type"),
        ))
    return events


async def _job_events(job_id, cursor: int, request: Request):
    """订阅任务广播；先用持久化状态恢复，再续传增量事件。"""
    hub = get_hub()
    queue = hub.subscribe(job_id)
    try:
        with SessionLocal() as snapshot:
            job = snapshot.get(AnswerJob, job_id)
            if job is None:
                return
            stage = job.current_stage
            content = job.partial_content or ""
            metrics = dict(job.metrics or {})
            status = job.status.value if hasattr(job.status, "value") else str(job.status)
            sources_payload = metrics.get("sources") or []
        if stage:
            yield encode_sse(AnswerEvent(type="stage", stage=stage))
        if sources_payload:
            yield encode_sse(AnswerEvent(
                type="sources", sources=[AnswerSource(**item) for item in sources_payload],
            ))
        if content:
            yield encode_sse(AnswerEvent(type="replace", text=""))
            chunk = content[cursor:] if 0 < cursor < len(content) else content
            yield encode_sse(AnswerEvent(type="delta", text=chunk))
            cursor = len(content)
        if status in {item.value for item in TERMINAL_STATUSES}:
            for event in _terminal_events(job, sources_payload):
                yield encode_sse(event)
            return
        while True:
            if await request.is_disconnected():
                break
            message = await queue.get()
            if message.done:
                break
            event = message.event
            if event is None:
                continue
            if event.type == "delta":
                if message.cursor and message.cursor <= cursor:
                    continue
                cursor = message.cursor
            yield encode_sse(event)
    finally:
        hub.unsubscribe(job_id, queue)


def _harness_event_stream(body: AnswerRequest, request: Request, session: Session, chat_user, recorder: AnswerRecorder):
    """Harness 运维问答仍按原同步流式处理（写操作逐次人工确认）。"""
    service = HarnessService(session, request.app.state.settings, user=chat_user)

    async def events():
        text_parts: list[str] = []
        sources: list = []
        metrics_payload: dict | None = None
        finalized = False
        stream = service.start(body)
        try:
            while True:
                try:
                    event = await stream.__anext__()
                except StopAsyncIteration:
                    break
                if await request.is_disconnected():
                    break
                if event.type == "sources" and event.sources is not None:
                    sources = event.sources
                elif event.type == "metrics" and event.metrics is not None:
                    metrics_payload = event.metrics
                elif event.type == "replace":
                    text_parts.clear()
                elif event.type == "delta" and event.text:
                    text_parts.append(event.text)
                elif event.type == "harness_done":
                    recorder.complete("".join(text_parts), ChatProvider.HARNESS, "INTERNAL", sources, metrics=metrics_payload)
                    finalized = True
                yield encode_sse(event)
        except asyncio.CancelledError:
            if not finalized:
                recorder.mark_stopped("".join(text_parts))
                finalized = True
            raise
        finally:
            if not finalized:
                recorder.mark_stopped("".join(text_parts))
            try:
                await stream.aclose()
            except (RuntimeError, asyncio.CancelledError):
                pass

    return events()


@router.post("/stream")
async def answer_stream(
    body: AnswerRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[RagService, Depends(get_rag_service)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """创建或复用生成任务，并订阅 SSE；生成在后台进行，不随浏览器连接中断。"""
    chat_user = require_permission(getattr(request.state, "auth_user", None), ANSWER_USE)
    body = apply_assistant_runtime_policy(session, body, chat_user)
    if body.use_harness and (chat_user is None or not chat_user.is_super_admin):
        raise AppError("HARNESS_FORBIDDEN", "Harness 功能仅限管理员使用", 403)
    chat = ChatService(session, user=chat_user)
    if body.session_id is not None:
        try:
            chat.get(body.session_id, include_archived=True)
        except KeyError as exc:
            raise AppError("CHAT_SESSION_NOT_FOUND", "会话不存在", 404) from exc

    job_service = AnswerJobService(session, user=chat_user)
    existing_job = job_service.get_by_request_id(body.request_id)
    if existing_job is not None:
        # 幂等：同一 request_id 直接复用已有任务，不重复创建用户/助手消息。
        _assert_job_access(existing_job, chat_user)
        job = existing_job
        session_id_value = job.conversation_id
        message_id_value = job.message_id
    else:
        recorder = AnswerRecorder(session, user=chat_user)
        if body.regenerate_message_id is not None:
            try:
                prepared = recorder.begin_regenerate(body.regenerate_message_id)
            except KeyError as exc:
                raise AppError("CHAT_MESSAGE_NOT_FOUND", "待重新生成的回答不存在", 404) from exc
        else:
            prepared = recorder.prepare(body.question, body.session_id, assistant_id=body.assistant_id)

        if body.use_harness:
            return StreamingResponse(
                _harness_event_stream(body, request, session, chat_user, recorder),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                    "X-Chat-Session-Id": str(prepared.id),
                    "X-Chat-Message-Id": str(recorder.assistant.id) if recorder.assistant else "",
                },
            )

        session_id_value = prepared.id
        message_id_value = recorder.assistant.id if recorder.assistant else None
        job, _created = job_service.create_or_get(
            conversation_id=session_id_value, message_id=message_id_value,
            user_id=chat_user.id, assistant_id=body.assistant_id, request_id=body.request_id,
        )

    job_id = job.id
    status_value = job.status.value if hasattr(job.status, "value") else str(job.status)
    if status_value not in {item.value for item in TERMINAL_STATUSES} and job_id not in RUNNING_TASKS:
        task = asyncio.create_task(run_answer_job(job_id, body, chat_user.id))
        RUNNING_TASKS[job_id] = task
        task.add_done_callback(lambda _task, jid=job_id: RUNNING_TASKS.pop(jid, None))

    try:
        cursor = int(last_event_id) if last_event_id else 0
    except (TypeError, ValueError):
        cursor = 0
    if cursor < 0:
        cursor = 0

    return StreamingResponse(
        _job_events(job_id, cursor, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Chat-Session-Id": str(session_id_value or ""),
            "X-Chat-Message-Id": str(message_id_value or ""),
            "X-Answer-Job-Id": str(job_id),
        },
    )


@router.get("/jobs/{job_id}/stream")
async def resume_answer_job_stream(
    job_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """断线/刷新后按游标续传同一生成任务的输出，不重新创建任务。"""
    chat_user = require_permission(getattr(request.state, "auth_user", None), ANSWER_USE)
    parsed = _parse_job_id(job_id)
    job = AnswerJobService(session, user=chat_user).get(parsed)
    _assert_job_access(job, chat_user)
    try:
        cursor = int(last_event_id) if last_event_id else 0
    except (TypeError, ValueError):
        cursor = 0
    return StreamingResponse(
        _job_events(parsed, max(0, cursor), request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Answer-Job-Id": str(parsed)},
    )


@router.get("/jobs/{job_id}", response_model=AnswerJobOut)
def get_answer_job(
    job_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AnswerJobOut:
    """查询生成任务状态；用于刷新页面后恢复。"""
    chat_user = require_permission(getattr(request.state, "auth_user", None), ANSWER_USE)
    job = AnswerJobService(session, user=chat_user).get(_parse_job_id(job_id))
    _assert_job_access(job, chat_user)
    return _job_out(job)


@router.post("/jobs/{job_id}/cancel", response_model=AnswerJobOut)
def cancel_answer_job(
    job_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AnswerJobOut:
    """只有用户显式点击“停止生成”时才取消任务。"""
    chat_user = require_permission(getattr(request.state, "auth_user", None), ANSWER_USE)
    service = AnswerJobService(session, user=chat_user)
    parsed = _parse_job_id(job_id)
    job = service.get(parsed)
    _assert_job_access(job, chat_user)
    service.cancel(parsed)
    task = RUNNING_TASKS.get(parsed)
    if task is not None and not task.done():
        task.cancel()
    return _job_out(service.get(parsed))


@router.get("/sessions/{session_id}/active-job", response_model=AnswerJobOut | None)
def active_answer_job(
    session_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AnswerJobOut | None:
    """返回会话中未完成的生成任务；页面重新打开时用于恢复。"""
    chat_user = require_permission(getattr(request.state, "auth_user", None), ANSWER_USE)
    import uuid as _uuid

    try:
        parsed = _uuid.UUID(session_id)
    except ValueError as exc:
        raise AppError("CHAT_SESSION_NOT_FOUND", "会话不存在", 404) from exc
    try:
        ChatService(session, user=chat_user).get(parsed, include_archived=True)
    except KeyError as exc:
        raise AppError("CHAT_SESSION_NOT_FOUND", "会话不存在", 404) from exc
    job = AnswerJobService(session, user=chat_user).active_for_session(parsed)
    return _job_out(job) if job is not None else None


def _parse_job_id(value: str):
    import uuid as _uuid

    try:
        return _uuid.UUID(value)
    except ValueError as exc:
        raise AppError("ANSWER_JOB_NOT_FOUND", "生成任务不存在", 404) from exc


def _assert_job_access(job: AnswerJob, chat_user) -> None:
    if getattr(chat_user, "is_super_admin", False):
        return
    if job.user_id != getattr(chat_user, "id", None):
        raise AppError("ANSWER_JOB_FORBIDDEN", "无权查看该生成任务", 403)
