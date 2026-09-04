"""文档业务服务：协调数据库元数据、磁盘文件和后台处理任务。"""

import uuid

from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.errors import DocumentAlreadyProcessing, DocumentNotFound, DuplicateDocument
from app.models import Document, DocumentChunk, DocumentStatus, JobStatus, JobType, ProcessingJob
from app.schemas.documents import DocumentFilters
from app.services.file_types import detect_allowed_type
from app.services.managed_storage import ManagedStorage


class DocumentService:
    """实现文档用例，并保证数据库记录和受管磁盘文件尽量保持一致。"""

    def __init__(self, session: Session, storage: ManagedStorage):
        self.session = session
        self.storage = storage

    def upload(self, file: UploadFile) -> Document:
        """暂存并校验文件，按 SHA-256 去重，入库后创建异步解析任务。"""
        staged = self.storage.stage(file.file, file.filename or "")
        promoted_path: str | None = None
        try:
            file_type = detect_allowed_type(staged.temp_path, staged.original_name)
            # 内容哈希比文件名可靠：同一内容即使改名也不会重复占用磁盘。
            duplicate = self.session.scalar(select(Document).where(Document.sha256 == staged.sha256))
            if duplicate:
                raise DuplicateDocument(str(duplicate.id))

            document = Document(
                id=uuid.uuid4(), original_name=staged.original_name,
                stored_path="", extension=file_type.extension, mime_type=file_type.mime_type,
                size_bytes=staged.size_bytes, sha256=staged.sha256, status=DocumentStatus.PENDING,
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
        clauses = [Document.status != DocumentStatus.DELETING]
        if filters.query:
            clauses.append(Document.original_name.ilike(f"%{filters.query}%"))
        if filters.extension:
            clauses.append(Document.extension == filters.extension.lower().lstrip("."))
        if filters.status:
            clauses.append(Document.status == filters.status)
        count = self.session.scalar(select(func.count()).select_from(Document).where(*clauses)) or 0
        documents = list(self.session.scalars(
            select(Document).where(*clauses).order_by(Document.created_at.desc(), Document.id.desc())
            .offset((filters.page - 1) * filters.page_size).limit(filters.page_size)
        ))
        return documents, count

    def get(self, document_id: uuid.UUID, include_deleting: bool = False) -> Document:
        clauses = [Document.id == document_id]
        if not include_deleting:
            clauses.append(Document.status != DocumentStatus.DELETING)
        document = self.session.scalar(select(Document).options(selectinload(Document.jobs)).where(*clauses))
        if not document:
            raise DocumentNotFound()
        return document

    def delete(self, document_id: uuid.UUID) -> None:
        document = self.get(document_id)
        document.status = DocumentStatus.DELETING
        self.session.commit()
        try:
            self.storage.delete(document.stored_path)
            self.session.delete(document)
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            document = self.get(document_id, include_deleting=True)
            document.error_code = "FILE_DELETE_FAILED"
            document.error_message = str(exc)
            self.session.commit()
            raise

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
