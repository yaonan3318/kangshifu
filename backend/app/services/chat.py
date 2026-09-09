"""聊天会话与回答记录服务：会话生命周期、消息/引用读取以及流式回答落库。"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ChatMessage, ChatMessageRole, ChatMessageSource, ChatMessageStatus, ChatProvider,
    ChatSession, Document, DocumentChunk, DocumentStatus, KnowledgeBase,
)
from app.schemas.answer import AnswerEvent, AnswerSource

DEFAULT_TITLE = "新会话"


def default_title_for(question: str, limit: int = 40) -> str:
    """从用户首个问题生成简洁会话标题。"""
    cleaned = " ".join(question.strip().split())
    return cleaned if len(cleaned) <= limit else f"{cleaned[:limit]}…"


class ChatService:
    """围绕 chat_sessions/chat_messages 的读接口与生命周期管理。"""

    def __init__(self, session: Session):
        self.session = session

    def create(self, title: str | None = None, assistant_id: uuid.UUID | None = None) -> ChatSession:
        session = ChatSession(title=(title or DEFAULT_TITLE).strip() or DEFAULT_TITLE)
        if assistant_id is not None:
            session.assistant_id = assistant_id
        self.session.add(session)
        self.session.commit()
        self.session.refresh(session)
        return session

    def get(self, session_id: uuid.UUID, include_archived: bool = False) -> ChatSession:
        statement = select(ChatSession).where(ChatSession.id == session_id)
        if not include_archived:
            statement = statement.where(ChatSession.archived_at.is_(None))
        session = self.session.scalar(statement)
        if session is None:
            raise KeyError("会话不存在")
        return session

    def list_sessions(
        self, search: str | None = None, archived: bool | None = None,
        limit: int = 50, offset: int = 0,
    ) -> tuple[list[ChatSession], int]:
        filters = []
        if search:
            filters.append(ChatSession.title.ilike(f"%{search.strip()}%"))
        if archived is True:
            filters.append(ChatSession.archived_at.is_not(None))
        elif archived is None:
            filters.append(ChatSession.archived_at.is_(None))
        base = select(ChatSession).where(*filters)
        total = self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.session.scalars(
            base.order_by(ChatSession.updated_at.desc()).limit(limit).offset(offset)
        ).all()
        return list(rows), total

    def rename(self, session_id: uuid.UUID, title: str) -> ChatSession:
        session = self.get(session_id)
        session.title = title.strip()[:255]
        self.session.commit()
        self.session.refresh(session)
        return session

    def archive(self, session_id: uuid.UUID) -> ChatSession:
        session = self.get(session_id)
        session.archived_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(session)
        return session

    def restore(self, session_id: uuid.UUID) -> ChatSession:
        session = self.get(session_id, include_archived=True)
        session.archived_at = None
        self.session.commit()
        self.session.refresh(session)
        return session

    def purge(self, session_id: uuid.UUID) -> None:
        session = self.get(session_id, include_archived=True)
        self.session.delete(session)
        self.session.commit()

    def messages(self, session_id: uuid.UUID) -> list[ChatMessage]:
        return list(self.session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .options(selectinload(ChatMessage.sources))
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        ))

    def message_count(self, session_id: uuid.UUID) -> int:
        return self.session.scalar(
            select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id == session_id)
        ) or 0

    def last_preview(self, session_id: uuid.UUID) -> str | None:
        message = self.session.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == session_id, ChatMessage.role == ChatMessageRole.USER,
            ).order_by(ChatMessage.created_at.desc()).limit(1)
        )
        return (message.content[:80] + "…") if message and len(message.content) > 80 else (message.content if message else None)

    def hydrate_source(self, source: ChatMessageSource) -> dict[str, Any]:
        """给来源快照附加当前可用状态，用于标记“当前资料已停用”。"""
        document, chunk, kb = self._current_state(source.document_id, source.chunk_id)
        available, status = self._availability(document, chunk, kb)
        return {
            "id": source.id,
            "citation_number": source.citation_number,
            "document_id": source.document_id,
            "chunk_id": source.chunk_id,
            "document_name": source.document_name,
            "content_snapshot": source.content_snapshot,
            "location_snapshot": source.location_snapshot,
            "score": source.score,
            "available": available,
            "status": status,
        }

    def _current_state(self, document_id: uuid.UUID, chunk_id: uuid.UUID):
        document = self.session.get(Document, document_id)
        chunk = self.session.get(DocumentChunk, chunk_id)
        kb = None
        if document is not None and document.knowledge_base_id is not None:
            kb = self.session.get(KnowledgeBase, document.knowledge_base_id)
        return document, chunk, kb

    @staticmethod
    def _availability(document, chunk, kb) -> tuple[bool, str]:
        if document is None or chunk is None:
            return False, "DELETED"
        superseded = bool(document.previous_version_id) or (
            kb is not None and not kb.enabled
        )
        active = (
            document.status == DocumentStatus.READY and document.enabled
            and document.deleted_at is None and chunk.enabled and not superseded
        )
        if active and kb is not None and kb.enabled:
            return True, "ACTIVE"
        return False, "DISABLED"


class AnswerRecorder:
    """把一次流式问答写入数据库：用户问题立即落库，助手答案完成后更新并保存引用快照。"""

    def __init__(self, session: Session):
        self.session = session
        self.session_row: ChatSession | None = None
        self.assistant: ChatMessage | None = None

    def prepare(self, question: str, session_id: uuid.UUID | None, assistant_id: uuid.UUID | None = None) -> ChatSession:
        """创建/复用会话并写入用户消息与处于生成中的助手消息。"""
        service = ChatService(self.session)
        if session_id is None:
            self.session_row = service.create(default_title_for(question))
        else:
            self.session_row = service.get(session_id)
            if self.session_row.title == DEFAULT_TITLE:
                self.session_row.title = default_title_for(question)
        if assistant_id is not None:
            self.session_row.assistant_id = assistant_id
        now = datetime.now(UTC)
        self.session_row.last_message_at = now
        self.session.add(self.session_row)

        user_message = ChatMessage(
            session_id=self.session_row.id, role=ChatMessageRole.USER,
            content=question.strip(), status=ChatMessageStatus.COMPLETED,
            provider=None, created_at=now,
        )
        self.session.add(user_message)

        self.assistant = ChatMessage(
            session_id=self.session_row.id, role=ChatMessageRole.ASSISTANT,
            content="", status=ChatMessageStatus.GENERATING,
            provider=ChatProvider.LOCAL, created_at=now + timedelta(microseconds=2),
        )
        self.session.add(self.assistant)
        self.session.commit()
        self.session.refresh(self.session_row)
        self.session.refresh(self.assistant)
        return self.session_row

    def begin_regenerate(self, message_id: uuid.UUID) -> ChatSession:
        """清空既有助手回答并重新进入生成状态，避免重复记录同一问题。"""
        assistant = self.session.get(ChatMessage, message_id)
        if assistant is None or assistant.role != ChatMessageRole.ASSISTANT:
            raise KeyError("待重新生成的回答不存在")
        session_row = assistant.session
        if session_row is None:
            raise KeyError("会话不存在")
        self.session.query(ChatMessageSource).filter(
            ChatMessageSource.message_id == assistant.id
        ).delete(synchronize_session=False)
        assistant.content = ""
        assistant.status = ChatMessageStatus.GENERATING
        assistant.provider = ChatProvider.LOCAL
        assistant.knowledge_scope = None
        assistant.error_code = None
        assistant.error_message = None
        assistant.completed_at = None
        self.session_row = session_row
        self.assistant = assistant
        self.session.commit()
        self.session.refresh(session_row)
        return session_row

    def mark_stopped(self, content: str) -> ChatMessage:
        return self._finish(content, ChatMessageStatus.STOPPED)

    def mark_failed(self, content: str, code: str, message: str) -> ChatMessage:
        return self._finish(content, ChatMessageStatus.FAILED, code=code, message=message)

    def complete(self, content: str, provider: ChatProvider, scope: str | None, sources: list[AnswerSource], metrics: dict | None = None) -> ChatMessage:
        self._finish(content, ChatMessageStatus.COMPLETED, provider=provider)
        if self.assistant is not None:
            self.assistant.knowledge_scope = scope
            if metrics:
                self.assistant.metrics = metrics
            for source in sources:
                self.session.add(ChatMessageSource(
                    message_id=self.assistant.id,
                    document_id=source.document_id,
                    chunk_id=source.chunk_id,
                    citation_number=source.citation_number,
                    document_name=source.document_name,
                    content_snapshot=source.content,
                    location_snapshot=RagLocation.location(source),
                    score=source.score,
                ))
        self.session.commit()
        if self.assistant is not None:
            self.session.refresh(self.assistant)
        return self.assistant

    def _finish(
        self, content: str, status: ChatMessageStatus,
        provider: ChatProvider | None = None, code: str | None = None, message: str | None = None,
    ) -> ChatMessage:
        if self.assistant is None:
            return None
        self.assistant.content = content
        self.assistant.status = status
        if provider is not None:
            self.assistant.provider = provider
        if code is not None:
            self.assistant.error_code = code
        if message is not None:
            self.assistant.error_message = message
        if status in (ChatMessageStatus.COMPLETED, ChatMessageStatus.FAILED, ChatMessageStatus.STOPPED):
            self.assistant.completed_at = datetime.now(UTC)
        self.session.commit()
        return self.assistant


class RagLocation:
    """把 AnswerSource 转成可读的位置快照，页面无需依赖仍存在的切片即可还原引用位置。"""

    @staticmethod
    def location(source: AnswerSource) -> dict[str, Any]:
        return {
            "page_start": source.page_start,
            "page_end": source.page_end,
            "slide_number": source.slide_number,
            "sheet_name": source.sheet_name,
            "row_start": source.row_start,
            "row_end": source.row_end,
            "section_path": source.section_path,
            "sequence_number": source.sequence_number,
            "extension": source.extension,
            "match_type": source.match_type,
            "text": RagLocation.text(source),
        }

    @staticmethod
    def text(source: AnswerSource) -> str:
        if source.page_start:
            return f"第 {source.page_start} 页"
        if source.slide_number:
            return f"第 {source.slide_number} 张幻灯片"
        if source.sheet_name:
            return f"{source.sheet_name}，第 {source.row_start or '?'} 行起"
        return f"片段 {source.sequence_number}"
