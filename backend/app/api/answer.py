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
    return RagService(session, settings)


def encode_sse(event: AnswerEvent) -> str:
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


@router.get("/status", response_model=AnswerStatusResponse)
async def answer_status(service: Annotated[RagService, Depends(get_rag_service)]) -> AnswerStatusResponse:
    return await service.status()


@router.post("/stream")
async def answer_stream(
    body: AnswerRequest,
    request: Request,
    service: Annotated[RagService, Depends(get_rag_service)],
) -> StreamingResponse:
    async def events():
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
