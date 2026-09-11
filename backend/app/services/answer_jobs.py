"""P2-5 生成任务服务：持久化 Answer Job、进程内事件广播与未完成任务恢复。

生成任务独立于浏览器连接：后台任务持续写入 job 的 current_stage / partial_content，
SSE 只负责订阅广播；页面刷新或断网后可按游标续传，服务重启后未完成任务标记为失败。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    AnswerJob, AnswerJobStatus, ChatMessage, ChatMessageRole, ChatMessageStatus, TERMINAL_STATUSES,
)


@dataclass
class JobMessage:
    """广播给订阅者的消息；cursor 为已产出的内容片段序号，用于断线去重。"""

    event: object | None = None
    cursor: int = 0
    done: bool = False


class AnswerJobHub:
    """进程内发布/订阅；每个任务可被多个浏览器连接订阅。"""

    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue]] = {}

    def subscribe(self, job_id: uuid.UUID) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(job_id, set()).add(queue)
        return queue

    def unsubscribe(self, job_id: uuid.UUID, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(job_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(job_id, None)

    def publish(self, job_id: uuid.UUID, message: JobMessage) -> None:
        for queue in list(self._subscribers.get(job_id, ())):
            queue.put_nowait(message)

    def finish(self, job_id: uuid.UUID) -> None:
        for queue in list(self._subscribers.get(job_id, ())):
            queue.put_nowait(JobMessage(done=True))


_hub = AnswerJobHub()
# 正在运行的后台任务；用于避免同一任务重复启动。
RUNNING_TASKS: dict[uuid.UUID, asyncio.Task] = {}


def get_hub() -> AnswerJobHub:
    return _hub


class AnswerJobService:
    def __init__(self, session: Session, user=None):
        self.session = session
        self.user = user

    def get(self, job_id: uuid.UUID) -> AnswerJob:
        value = self.session.get(AnswerJob, job_id)
        if value is None:
            raise AppError("ANSWER_JOB_NOT_FOUND", "生成任务不存在", 404)
        return value

    def get_by_request_id(self, request_id: str | None) -> AnswerJob | None:
        if not request_id:
            return None
        return self.session.scalar(select(AnswerJob).where(AnswerJob.request_id == request_id))

    def create_or_get(
        self, *, conversation_id: uuid.UUID | None, message_id: uuid.UUID | None,
        user_id: uuid.UUID | None, assistant_id: uuid.UUID | None, request_id: str | None,
    ) -> tuple[AnswerJob, bool]:
        """幂等创建：相同 request_id 或同一消息的未完成任务直接复用。"""
        if request_id:
            existing = self.session.scalar(select(AnswerJob).where(AnswerJob.request_id == request_id))
            if existing is not None:
                return existing, False
        if message_id is not None:
            existing = self.session.scalar(
                select(AnswerJob).where(
                    AnswerJob.message_id == message_id,
                    AnswerJob.status.notin_(list(TERMINAL_STATUSES)),
                ).order_by(AnswerJob.created_at.desc()).limit(1)
            )
            if existing is not None:
                return existing, False
        job = AnswerJob(
            conversation_id=conversation_id, message_id=message_id,
            user_id=user_id, assistant_id=assistant_id, request_id=request_id,
            status=AnswerJobStatus.PENDING,
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job, True

    def mark_started(self, job_id: uuid.UUID) -> None:
        job = self.get(job_id)
        job.status = AnswerJobStatus.RETRIEVING
        job.started_at = job.started_at or datetime.now(UTC)
        self.session.commit()

    def update_stage(self, job_id: uuid.UUID, stage: str | None, status: AnswerJobStatus | None = None) -> None:
        job = self.get(job_id)
        if stage:
            job.current_stage = stage
        if status is not None:
            job.status = status
        self.session.commit()

    def append_content(self, job_id: uuid.UUID, text: str) -> int:
        """追加内容并返回当前内容长度（作为断线续传游标）。"""
        job = self.get(job_id)
        job.partial_content = (job.partial_content or "") + text
        job.event_cursor = len(job.partial_content)
        self.session.commit()
        return job.event_cursor

    def replace_content(self, job_id: uuid.UUID) -> None:
        job = self.get(job_id)
        job.partial_content = ""
        self.session.commit()

    def set_metrics(self, job_id: uuid.UUID, patch: dict) -> None:
        job = self.get(job_id)
        merged = dict(job.metrics or {})
        merged.update(patch)
        job.metrics = merged
        self.session.commit()

    def finish(
        self, job_id: uuid.UUID, status: AnswerJobStatus,
        error_code: str | None = None, error_message: str | None = None,
    ) -> None:
        job = self.get(job_id)
        job.status = status
        job.error_code = error_code
        job.error_message = error_message
        now = datetime.now(UTC)
        if status == AnswerJobStatus.CANCELLED:
            job.cancelled_at = now
        else:
            job.completed_at = now
        self.session.commit()

    def cancel(self, job_id: uuid.UUID) -> AnswerJob:
        job = self.get(job_id)
        if job.status in TERMINAL_STATUSES:
            return job
        job.status = AnswerJobStatus.CANCELLED
        job.cancelled_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(job)
        return job

    def active_for_session(self, session_id: uuid.UUID) -> AnswerJob | None:
        return self.session.scalar(
            select(AnswerJob).where(
                AnswerJob.conversation_id == session_id,
                AnswerJob.status.notin_(list(TERMINAL_STATUSES)),
            ).order_by(AnswerJob.created_at.desc()).limit(1)
        )

    def is_cancelled(self, job_id: uuid.UUID) -> bool:
        job = self.session.get(AnswerJob, job_id)
        return job is None or job.status == AnswerJobStatus.CANCELLED

    def recover_stale(self) -> int:
        """服务重启后，未完成的生成任务无法继续，统一标记为失败并同步消息状态。"""
        jobs = list(self.session.scalars(
            select(AnswerJob).where(AnswerJob.status.notin_(list(TERMINAL_STATUSES)))
        ))
        for job in jobs:
            job.status = AnswerJobStatus.FAILED
            job.error_code = "ANSWER_INTERRUPTED"
            job.error_message = "服务重启导致生成任务中断，请重新生成"
            job.completed_at = datetime.now(UTC)
            if job.message_id is not None:
                message = self.session.get(ChatMessage, job.message_id)
                if message is not None and message.role == ChatMessageRole.ASSISTANT:
                    message.status = ChatMessageStatus.FAILED
                    message.error_code = "ANSWER_INTERRUPTED"
                    message.error_message = "服务重启导致生成任务中断，请重新生成"
        self.session.commit()
        return len(jobs)
