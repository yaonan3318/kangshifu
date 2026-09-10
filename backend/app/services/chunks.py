"""片段治理业务：编辑、启停和原子重建全文/向量索引。"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.models import Document, DocumentChunk
from app.services.embeddings import EmbeddingService
from app.services.keywords import keyword_text
from app.services.permissions import PermissionResolver, require_manage, require_read


class ChunkService:
    def __init__(self, session: Session, settings: Settings, user=None):
        self.session = session
        self.embeddings = EmbeddingService(settings)
        self.resolver = PermissionResolver(session, user) if user is not None else None

    def _check_read(self, document: Document) -> None:
        if self.resolver is not None:
            require_read(self.resolver, document)

    def _check_manage(self, document: Document) -> None:
        if self.resolver is not None:
            require_manage(self.resolver, document)

    def list_chunks(self, document_id: uuid.UUID, page: int, page_size: int) -> tuple[list[DocumentChunk], int]:
        document = self._active_document(document_id)
        self._check_read(document)
        clause = DocumentChunk.document_id == document_id
        total = self.session.scalar(select(func.count()).select_from(DocumentChunk).where(clause)) or 0
        items = list(self.session.scalars(
            select(DocumentChunk).where(clause).order_by(DocumentChunk.sequence_number)
            .offset((page - 1) * page_size).limit(page_size)
        ))
        return items, total

    def get(self, chunk_id: uuid.UUID) -> DocumentChunk:
        value = self.session.scalar(
            select(DocumentChunk).join(Document).where(
                DocumentChunk.id == chunk_id,
                Document.deleted_at.is_(None),
            )
        )
        if not value:
            raise AppError("CHUNK_NOT_FOUND", "片段不存在", 404)
        return value

    def update_content(self, chunk_id: uuid.UUID, content: str) -> DocumentChunk:
        chunk = self.get(chunk_id)
        self._check_manage(chunk.document)
        clean = content.strip()
        if not clean:
            raise AppError("EMPTY_CHUNK", "片段内容不能为空", 400)
        vector, search_text, token_count = self._build_index(chunk, clean)
        if chunk.original_content is None:
            chunk.original_content = chunk.content
        chunk.content = clean
        chunk.embedding = vector
        chunk.search_vector = func.to_tsvector("simple", search_text)
        chunk.token_count = token_count
        chunk.manually_edited = True
        self.session.commit()
        self.session.refresh(chunk)
        return chunk

    def restore_original(self, chunk_id: uuid.UUID) -> DocumentChunk:
        chunk = self.get(chunk_id)
        self._check_manage(chunk.document)
        if chunk.original_content is None:
            raise AppError("CHUNK_NOT_EDITED", "片段没有可恢复的原始内容", 409)
        original = chunk.original_content
        vector, search_text, token_count = self._build_index(chunk, original)
        chunk.content = original
        chunk.original_content = None
        chunk.embedding = vector
        chunk.search_vector = func.to_tsvector("simple", search_text)
        chunk.token_count = token_count
        chunk.manually_edited = False
        self.session.commit()
        self.session.refresh(chunk)
        return chunk

    def reindex(self, chunk_id: uuid.UUID) -> DocumentChunk:
        chunk = self.get(chunk_id)
        self._check_manage(chunk.document)
        vector, search_text, token_count = self._build_index(chunk, chunk.content)
        chunk.embedding = vector
        chunk.search_vector = func.to_tsvector("simple", search_text)
        chunk.token_count = token_count
        self.session.commit()
        self.session.refresh(chunk)
        return chunk

    def set_enabled(self, chunk_id: uuid.UUID, enabled: bool) -> DocumentChunk:
        chunk = self.get(chunk_id)
        self._check_manage(chunk.document)
        chunk.enabled = enabled
        self.session.commit()
        self.session.refresh(chunk)
        return chunk

    def _build_index(self, chunk: DocumentChunk, content: str) -> tuple[list[float], str, int]:
        # 所有耗时计算先完成，再修改 ORM 对象，模型异常时事务中没有半成品。
        vector = self.embeddings.encode_documents([content])[0]
        document = chunk.document
        search_text = keyword_text(" ".join([document.original_name, *chunk.section_path, content]))
        return vector, search_text, len(search_text.split())

    def _active_document(self, document_id: uuid.UUID) -> Document:
        value = self.session.scalar(select(Document).where(Document.id == document_id, Document.deleted_at.is_(None)))
        if not value:
            raise AppError("DOCUMENT_NOT_FOUND", "文档不存在", 404)
        return value
