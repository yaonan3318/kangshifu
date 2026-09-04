"""RAG 问答接口，以 Server-Sent Events (SSE) 持续推送生成结果。"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.schemas.answer import AnswerEvent, AnswerRequest, AnswerStatusResponse
from app.services.rag import RagService

router = APIRouter(prefix="/api/answer", tags=["answer"])
logger = logging.getLogger(__name__)


def get_rag_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RagService:
    """为当前请求创建 RAG 编排服务，并复用请求级数据库 Session。"""
    return RagService(session, settings)


def encode_sse(event: AnswerEvent) -> str:
    """把 Pydantic 事件编码成浏览器 EventSource/fetch 可读取的 SSE 帧。"""
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


@router.get("/status", response_model=AnswerStatusResponse)
async def answer_status(service: Annotated[RagService, Depends(get_rag_service)]) -> AnswerStatusResponse:
    """检查本地 Ollama 模型是否就绪以及 DeepSeek 是否已配置。"""
    return await service.status()


@router.post("/stream")
async def answer_stream(
    body: AnswerRequest,
    request: Request,
    service: Annotated[RagService, Depends(get_rag_service)],
) -> StreamingResponse:
    """先检索内部资料，再流式返回千问答案，并按需用 DeepSeek 替换增强答案。"""
    async def events():
        # 客户端关闭页面后尽快停止生成，避免模型继续占用计算资源。
        try:
            async for event in service.stream(body):
                if await request.is_disconnected():
                    return
                yield encode_sse(event)
        except Exception as exc:
            logger.exception("RAG answer stream failed", exc_info=exc)
            yield encode_sse(AnswerEvent(
                type="error",
                error={"code": "ANSWER_FAILED", "message": "问答处理失败，请查看本地后端日志"},
            ))

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
