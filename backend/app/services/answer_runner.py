"""P2-5 后台生成任务：在独立数据库会话中运行 RAG，并把状态写入 Answer Job。

任务不依赖浏览器连接；SSE 端点只是订阅广播。取消通过任务取消 + 状态标记实现。
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from app.config import get_settings
from app.db import SessionLocal
from app.models import AnswerJobStatus, ChatProvider, User
from app.schemas.answer import AnswerEvent
from app.services.answer_jobs import AnswerJobService, JobMessage, get_hub
from app.services.audit import record as audit_record
from app.services.chat import AnswerRecorder
from app.services.knowledge_gaps import record_gap
from app.services.rag import RagService
from app.services.retrieval_config import load_active_config

logger = logging.getLogger(__name__)

# 允许测试注入替身，避免后台任务访问真实模型。
RAG_FACTORY = RagService

_STAGE_STATUS = {
    "understanding": AnswerJobStatus.RETRIEVING,
    "rewriting": AnswerJobStatus.RETRIEVING,
    "retrieving": AnswerJobStatus.RETRIEVING,
    "candidates": AnswerJobStatus.RETRIEVING,
    "reranking": AnswerJobStatus.RETRIEVING,
    "local_generating": AnswerJobStatus.GENERATING,
    "deepseek_enhancing": AnswerJobStatus.GENERATING,
    "checking": AnswerJobStatus.VERIFYING,
}


def _provider_value(event: AnswerEvent) -> ChatProvider:
    if event.provider is None:
        return ChatProvider.LOCAL
    return ChatProvider(str(event.provider.value))


async def run_answer_job(job_id: uuid.UUID, body, user_id: uuid.UUID | None) -> None:
    """后台执行一次问答；状态与部分内容持续写入 Answer Job。"""
    session = SessionLocal()
    job_service = AnswerJobService(session)
    hub = get_hub()
    recorder: AnswerRecorder | None = None
    text_parts: list[str] = []
    sources: list = []
    metrics_payload: dict | None = None
    finalized = False
    try:
        job = job_service.get(job_id)
        if job.status == AnswerJobStatus.CANCELLED:
            hub.finish(job_id)
            return
        job_service.mark_started(job_id)
        user = session.get(User, user_id) if user_id else None
        settings = get_settings()
        config = load_active_config(session, settings)
        service = RAG_FACTORY(session, settings, user=user, config=config)
        recorder = AnswerRecorder(session, user=user)
        recorder.resume(job.message_id)
        async for event in service.stream(body):
            if job_service.is_cancelled(job_id):
                break
            if event.type == "stage":
                job_service.update_stage(job_id, event.stage, _STAGE_STATUS.get(event.stage or ""))
                if event.stage == "deepseek_enhancing":
                    audit_record(
                        session, "external_llm_requested", user=user,
                        target_type="chat_session", target_id=job.conversation_id,
                        detail={"document_ids": [str(item.document_id) for item in sources]},
                    )
            elif event.type == "delta" and event.text:
                cursor = job_service.append_content(job_id, event.text)
                text_parts.append(event.text)
                hub.publish(job_id, JobMessage(event=event, cursor=cursor))
                continue
            elif event.type == "replace":
                job_service.replace_content(job_id)
                text_parts.clear()
            elif event.type == "sources" and event.sources is not None:
                sources = event.sources
                job_service.set_metrics(job_id, {
                    "sources": [item.model_dump(mode="json") for item in sources],
                })
            elif event.type == "metrics" and event.metrics is not None:
                metrics_payload = event.metrics
                job_service.set_metrics(job_id, {"metrics": metrics_payload})
            elif event.type == "confidence" and event.confidence is not None:
                job_service.set_metrics(job_id, {
                    "confidence": event.confidence, "question_type": event.question_type,
                })
            elif event.type == "citation_check" and event.citation_check is not None:
                job_service.set_metrics(job_id, {"citation_check": event.citation_check})
            elif event.type == "no_answer" and event.no_answer is not None:
                job_service.set_metrics(job_id, {"no_answer": event.no_answer})
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
            elif event.type == "suggestions" and event.suggestions is not None:
                job_service.set_metrics(job_id, {"suggestions": event.suggestions})
            elif event.type == "warning" and event.warning is not None:
                _audit_warning(session, user, job, event)
            elif event.type == "done":
                content = "".join(text_parts)
                recorder.complete(
                    content, _provider_value(event),
                    event.scope.value if event.scope is not None else None,
                    sources, metrics=metrics_payload,
                )
                job_service.set_metrics(job_id, {"scope": event.scope.value if event.scope else None,
                                                 "provider": _provider_value(event).value})
                job_service.finish(job_id, AnswerJobStatus.COMPLETED)
                finalized = True
            elif event.type == "error" and event.error:
                recorder.mark_failed(
                    "".join(text_parts), event.error.get("code", "ANSWER_FAILED"),
                    event.error.get("message", "问答处理失败"),
                )
                job_service.finish(
                    job_id, AnswerJobStatus.FAILED,
                    event.error.get("code", "ANSWER_FAILED"), event.error.get("message"),
                )
                finalized = True
            hub.publish(job_id, JobMessage(event=event))
        if not finalized:
            if job_service.is_cancelled(job_id):
                recorder.mark_stopped("".join(text_parts))
                job_service.finish(job_id, AnswerJobStatus.CANCELLED)
            else:
                recorder.mark_failed("".join(text_parts), "ANSWER_INTERRUPTED", "生成任务意外结束")
                job_service.finish(job_id, AnswerJobStatus.FAILED, "ANSWER_INTERRUPTED", "生成任务意外结束")
    except asyncio.CancelledError:
        try:
            if recorder is not None and recorder.assistant is not None:
                recorder.mark_stopped("".join(text_parts))
            AnswerJobService(session).finish(job_id, AnswerJobStatus.CANCELLED)
        except Exception:
            logger.exception("Failed to finalize cancelled answer job %s", job_id)
        raise
    except Exception as exc:
        logger.exception("Answer job %s failed", job_id)
        try:
            if recorder is not None and recorder.assistant is not None:
                recorder.mark_failed("".join(text_parts), "ANSWER_FAILED", str(exc))
            AnswerJobService(session).finish(job_id, AnswerJobStatus.FAILED, "ANSWER_FAILED", str(exc))
        except Exception:
            logger.exception("Failed to persist answer job failure %s", job_id)
    finally:
        hub.finish(job_id)
        session.close()


def _audit_warning(session, user, job, event) -> None:
    warning = event.warning
    if warning.code in ("ASSISTANT_DEEPSEEK_BLOCKED", "EXTERNAL_LLM_BLOCKED", "DEEPSEEK_NOT_CONFIGURED"):
        audit_record(
            session, "external_llm_blocked", user=user,
            target_type="chat_session", target_id=job.conversation_id,
            detail={"reason": warning.code, "message": warning.message},
        )
    elif warning.code.startswith("DEEPSEEK_"):
        audit_record(
            session, "external_llm_failed", user=user,
            target_type="chat_session", target_id=job.conversation_id,
            detail={"error_code": warning.code, "message": warning.message},
            success=False, error_code=warning.code,
        )
