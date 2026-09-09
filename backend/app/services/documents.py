"""文档业务服务：协调数据库元数据、磁盘文件和后台处理任务。"""

import uuid
from datetime import UTC, datetime

from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.errors import DocumentAlreadyProcessing, DocumentNotFound, DuplicateDocument
from app.errors import AppError
from app.models import DEFAULT_KNOWLEDGE_BASE_ID, Document, DocumentChunk, DocumentStatus, JobStatus, JobType, KnowledgeBase, ProcessingJob, Tag
from app.schemas.documents import DocumentFilters, DocumentUpdateRequest
from app.services.file_types import detect_allowed_type
from app.services.managed_storage import ManagedStorage


class DocumentService:
    """实现文档用例，并保证数据库记录和受管磁盘文件尽量保持一致。"""

    def __init__(self, session: Session, storage: ManagedStorage):
        self.session = session
        self.storage = storage

    def upload(self, file: UploadFile, knowledge_base_id: uuid.UUID | None = None) -> Document:
        """暂存并校验文件，按 SHA-256 去重，入库后创建异步解析任务。"""
        staged = self.storage.stage(file.file, file.filename or "")
        promoted_path: str | None = None
        try:
            file_type = detect_allowed_type(staged.temp_path, staged.original_name)
            # 内容哈希比文件名可靠：同一内容即使改名也不会重复占用磁盘。
            duplicate = self.session.scalar(select(Document).where(Document.sha256 == staged.sha256))
            if duplicate:
                raise DuplicateDocument(str(duplicate.id))

            target_base = knowledge_base_id or DEFAULT_KNOWLEDGE_BASE_ID
            self._knowledge_base(target_base)
            document = Document(
                id=uuid.uuid4(), original_name=staged.original_name,
                stored_path="", extension=file_type.extension, mime_type=file_type.mime_type,
                size_bytes=staged.size_bytes, sha256=staged.sha256, status=DocumentStatus.PENDING,
                knowledge_base_id=target_base, relative_path=staged.original_name,
            )
            promoted_path = self.storage.promote(staged, document.id, file_type.extension)
            document.stored_path = promoted_path
            document.jobs.append(ProcessingJob(job_type=JobType.PARSE, status=JobStatus.QUEUED))
            self.session.add(document)
            self.session.commit()
            self.session.refresh(document)
            return document
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(select(Document).where(Document.sha256 == staged.sha256))
            if promoted_path:
                self.storage.delete(promoted_path)
            if existing:
                raise DuplicateDocument(str(existing.id)) from None
            raise
        except Exception:
            self.session.rollback()
            if promoted_path:
                self.storage.delete(promoted_path)
            raise
        finally:
            self.storage.discard(staged)

    def list_documents(self, filters: DocumentFilters) -> tuple[list[Document], int]:
        clauses = []
        if filters.include_deleted:
            clauses.append(Document.deleted_at.is_not(None))
        else:
            clauses.extend([Document.status != DocumentStatus.DELETING, Document.deleted_at.is_(None)])
        if filters.query:
            clauses.append(Document.original_name.ilike(f"%{filters.query}%"))
        if filters.extension:
            clauses.append(Document.extension == filters.extension.lower().lstrip("."))
        if filters.status:
            clauses.append(Document.status == filters.status)
        if filters.knowledge_base_id:
            clauses.append(Document.knowledge_base_id == filters.knowledge_base_id)
        if filters.tag:
            clauses.append(Document.tags.any(Tag.name == filters.tag.strip()))
        count = self.session.scalar(select(func.count()).select_from(Document).where(*clauses)) or 0
        documents = list(self.session.scalars(
            select(Document).options(selectinload(Document.tags)).where(*clauses).order_by(Document.created_at.desc(), Document.id.desc())
            .offset((filters.page - 1) * filters.page_size).limit(filters.page_size)
        ))
        return documents, count

    def get(self, document_id: uuid.UUID, include_deleted: bool = False) -> Document:
        clauses = [Document.id == document_id]
        if not include_deleted:
            clauses.extend([Document.status != DocumentStatus.DELETING, Document.deleted_at.is_(None)])
        document = self.session.scalar(select(Document).options(
            selectinload(Document.jobs), selectinload(Document.tags)
        ).where(*clauses))
        if not document:
            raise DocumentNotFound()
        return document

    def delete(self, document_id: uuid.UUID, reason: str | None = None) -> None:
        document = self.get(document_id)
        document.deleted_at = datetime.now(UTC)
        document.deleted_reason = reason.strip() if reason else None
        self.session.commit()

    def restore(self, document_id: uuid.UUID) -> Document:
        document = self.get(document_id, include_deleted=True)
        if document.deleted_at is None:
            raise AppError("DOCUMENT_NOT_DELETED", "文档不在回收站中", 409)
        document.deleted_at = None
        document.deleted_reason = None
        self.session.commit()
        self.session.refresh(document)
        return document

    def purge(self, document_id: uuid.UUID) -> None:
        document = self.get(document_id, include_deleted=True)
        if document.deleted_at is None:
            raise AppError("DOCUMENT_NOT_DELETED", "只有回收站中的文档才能永久删除", 409)
        try:
            self.storage.delete(document.stored_path)
            self.session.delete(document)
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            document = self.get(document_id, include_deleted=True)
            document.error_code = "FILE_DELETE_FAILED"
            document.error_message = str(exc)
            self.session.commit()
            raise

    def set_enabled(self, document_id: uuid.UUID, enabled: bool) -> Document:
        document = self.get(document_id)
        document.enabled = enabled
        self.session.commit()
        self.session.refresh(document)
        return document

    def update(self, document_id: uuid.UUID, body: DocumentUpdateRequest) -> Document:
        document = self.get(document_id)
        if body.knowledge_base_id is not None and body.knowledge_base_id != document.knowledge_base_id:
            self._knowledge_base(body.knowledge_base_id)
            document.knowledge_base_id = body.knowledge_base_id
            document.tags = []
        if body.relative_path is not None:
            document.relative_path = body.relative_path.strip() or document.original_name
        if body.metadata is not None:
            document.metadata_json = body.metadata
        if body.tags is not None:
            names = list(dict.fromkeys(name.strip() for name in body.tags if name.strip()))
            document.tags = [self._tag(document.knowledge_base_id, name) for name in names]
        self.session.commit()
        self.session.refresh(document)
        return self.get(document.id)

    def versions(self, document_id: uuid.UUID) -> list[Document]:
        document = self.get(document_id, include_deleted=True)
        root_id = document.id
        while document.previous_version_id:
            root_id = document.previous_version_id
            document = self.get(root_id, include_deleted=True)
        values = [document]
        frontier = [root_id]
        while frontier:
            children = list(self.session.scalars(select(Document).where(Document.previous_version_id.in_(frontier))))
            values.extend(children)
            frontier = [item.id for item in children]
        return sorted({item.id: item for item in values}.values(), key=lambda item: item.version_number, reverse=True)

    def chunk_count(self, document_id: uuid.UUID) -> int:
        return self.session.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == document_id)) or 0

    def _knowledge_base(self, knowledge_base_id: uuid.UUID) -> KnowledgeBase:
        value = self.session.scalar(select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id, KnowledgeBase.enabled.is_(True)))
        if not value:
            raise AppError("KNOWLEDGE_BASE_NOT_FOUND", "目标知识库不存在或已停用", 404)
        return value

    def _tag(self, knowledge_base_id: uuid.UUID, name: str) -> Tag:
        value = self.session.scalar(select(Tag).where(Tag.knowledge_base_id == knowledge_base_id, Tag.name == name))
        if value:
            return value
        value = Tag(knowledge_base_id=knowledge_base_id, name=name)
        self.session.add(value)
        return value

    def content(self, document_id: uuid.UUID, page: int, page_size: int) -> tuple[list[DocumentChunk], int]:
        self.get(document_id)
        clause = DocumentChunk.document_id == document_id
        total = self.session.scalar(select(func.count()).select_from(DocumentChunk).where(clause)) or 0
        chunks = list(self.session.scalars(
            select(DocumentChunk).where(clause).order_by(DocumentChunk.sequence_number)
            .offset((page - 1) * page_size).limit(page_size)
        ))
        return chunks, total

    def reprocess(self, document_id: uuid.UUID) -> Document:
        document = self.get(document_id)
        active = self.session.scalar(select(ProcessingJob.id).where(
            ProcessingJob.document_id == document_id,
            ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
        ))
        if active:
            raise DocumentAlreadyProcessing()
        self.session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        document.status = DocumentStatus.PENDING
        document.error_code = None
        document.error_message = None
        document.jobs.append(ProcessingJob(job_type=JobType.PARSE, status=JobStatus.QUEUED))
        self.session.commit()
        self.session.refresh(document)
        return document
