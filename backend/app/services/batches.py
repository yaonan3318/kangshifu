"""批次业务：逐文件提交、内容去重、失败隔离与进度汇总。"""
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import PurePosixPath
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.config import Settings
from app.errors import AppError, DocumentAlreadyProcessing
from app.models import DEFAULT_KNOWLEDGE_BASE_ID, BatchFile, BatchProcessingStatus, BatchStatus, BatchUploadStatus, Document, DocumentStatus, JobStatus, JobType, KnowledgeBase, ProcessingJob, UploadBatch
from app.schemas.batches import BatchDetailResponse, BatchResponse
from app.services.documents import DocumentService
from app.services.file_types import detect_allowed_type
from app.services.managed_storage import ManagedStorage

def processing_status(document: Document) -> BatchProcessingStatus:
    if document.status == DocumentStatus.READY: return BatchProcessingStatus.INDEXED
    if document.status == DocumentStatus.PARSED: return BatchProcessingStatus.PARSED
    if document.status in {DocumentStatus.INDEX_FAILED, DocumentStatus.PARSE_FAILED, DocumentStatus.OCR_FAILED}: return BatchProcessingStatus.FAILED
    return BatchProcessingStatus.PROCESSING

class BatchService:
    def __init__(self, session: Session, settings: Settings):
        self.session, self.settings, self.storage = session, settings, ManagedStorage(settings)

    def create(self, name: str, category: str | None, tags: list[str], note: str | None, files, knowledge_base_id: uuid.UUID | None = None) -> UploadBatch:
        if len(files) > self.settings.batch_max_files:
            raise AppError("BATCH_TOO_MANY_FILES", f"单个批次最多允许 {self.settings.batch_max_files} 个文件", 413)
        if sum(x.size_bytes for x in files) > self.settings.batch_max_total_bytes:
            raise AppError("BATCH_TOO_LARGE", "批次文件总容量超过配置上限", 413)
        target_base = knowledge_base_id or DEFAULT_KNOWLEDGE_BASE_ID
        if not self.session.scalar(select(KnowledgeBase.id).where(KnowledgeBase.id == target_base, KnowledgeBase.enabled.is_(True))):
            raise AppError("KNOWLEDGE_BASE_NOT_FOUND", "目标知识库不存在或已停用", 404)
        batch = UploadBatch(name=name.strip(), category=category.strip() if category else None,
            knowledge_base_id=target_base,
            tags=list(dict.fromkeys(x.strip() for x in tags if x.strip())), note=note)
        seen = set()
        for item in files:
            path = self._relative_path(item.relative_path)
            if path in seen: raise AppError("DUPLICATE_BATCH_PATH", f"批次中存在重复路径：{path}", 400)
            seen.add(path)
            batch.files.append(BatchFile(relative_path=path, original_name=PurePosixPath(path).name, size_bytes=item.size_bytes))
        self.session.add(batch); self.session.commit(); self.session.refresh(batch); return batch

    def get(self, batch_id: uuid.UUID) -> UploadBatch:
        batch = self.session.scalar(select(UploadBatch).where(UploadBatch.id == batch_id).options(selectinload(UploadBatch.files).selectinload(BatchFile.document)))
        if not batch: raise AppError("BATCH_NOT_FOUND", "导入批次不存在", 404)
        self._synchronize(batch); return batch

    def list(self) -> list[UploadBatch]:
        values = list(self.session.scalars(select(UploadBatch).options(selectinload(UploadBatch.files).selectinload(BatchFile.document)).order_by(UploadBatch.created_at.desc())))
        for batch in values: self._synchronize(batch)
        self.session.commit(); return values

    def upload(self, batch_id: uuid.UUID, relative_path: str, file: UploadFile) -> BatchFile:
        batch = self.get(batch_id)
        if batch.status == BatchStatus.CANCELLED: raise AppError("BATCH_CANCELLED", "已取消的批次不能继续上传", 409)
        path = self._relative_path(relative_path or file.filename or "")
        row = next((x for x in batch.files if x.relative_path == path), None)
        if row and row.upload_status in {BatchUploadStatus.UPLOADED, BatchUploadStatus.DUPLICATE}: return row
        row = row or BatchFile(batch=batch, relative_path=path, original_name=PurePosixPath(path).name, size_bytes=0)
        row.upload_status, batch.status = BatchUploadStatus.UPLOADING, BatchStatus.UPLOADING
        row.error_stage = row.error_code = row.error_message = None
        self.session.add(row); self.session.commit(); self.session.refresh(row)
        staged = None; promoted = None
        try:
            self.settings.ensure_directories()
            if shutil.disk_usage(self.settings.library_root).free < self.settings.batch_min_free_bytes:
                raise AppError("INSUFFICIENT_DISK_SPACE", "本机剩余空间不足，无法继续导入", 507)
            staged = self.storage.stage(file.file, row.original_name)
            row.size_bytes, row.sha256 = staged.size_bytes, staged.sha256
            duplicate = self.session.scalar(select(Document).where(Document.sha256 == staged.sha256))
            if duplicate:
                row.document, row.upload_status = duplicate, BatchUploadStatus.DUPLICATE
                row.processing_status = processing_status(duplicate)
            else:
                kind = detect_allowed_type(staged.temp_path, staged.original_name)
                previous = self.session.scalar(select(Document).where(
                    Document.knowledge_base_id == batch.knowledge_base_id,
                    Document.relative_path == path,
                    Document.deleted_at.is_(None),
                ).order_by(Document.version_number.desc()).limit(1))
                document = Document(id=uuid.uuid4(), original_name=staged.original_name, stored_path="", extension=kind.extension,
                    mime_type=kind.mime_type, size_bytes=staged.size_bytes, sha256=staged.sha256, status=DocumentStatus.PENDING,
                    knowledge_base_id=batch.knowledge_base_id, relative_path=path,
                    previous_version_id=previous.id if previous else None,
                    version_number=(previous.version_number + 1) if previous else 1)
                promoted = self.storage.promote(staged, document.id, kind.extension); document.stored_path = promoted
                document.jobs.append(ProcessingJob(job_type=JobType.PARSE, status=JobStatus.QUEUED))
                row.document, row.upload_status, row.processing_status = document, BatchUploadStatus.UPLOADED, BatchProcessingStatus.WAITING
                self.session.add(document)
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            if promoted: self.storage.delete(promoted)
            row = self.session.get(BatchFile, row.id)
            row.upload_status, row.processing_status, row.error_stage = BatchUploadStatus.FAILED, BatchProcessingStatus.FAILED, "UPLOAD"
            row.error_code = exc.code if isinstance(exc, AppError) else "UPLOAD_FAILED"
            row.error_message = exc.message if isinstance(exc, AppError) else str(exc)
            self.session.commit(); raise
        finally:
            if staged: self.storage.discard(staged)
        self._synchronize(self.get(batch_id)); self.session.commit(); return self.session.get(BatchFile, row.id)

    def retry(self, batch_id: uuid.UUID, file_id: uuid.UUID) -> BatchFile:
        row = self._file(batch_id, file_id); row.retry_count += 1
        if not row.document_id or row.error_stage == "UPLOAD":
            row.upload_status, row.processing_status = BatchUploadStatus.PENDING, BatchProcessingStatus.WAITING
        else:
            try: DocumentService(self.session, self.storage).reprocess(row.document_id)
            except DocumentAlreadyProcessing: pass
            row.processing_status = BatchProcessingStatus.PROCESSING
        row.error_stage = row.error_code = row.error_message = None
        self.session.commit(); return row

    def ignore(self, batch_id: uuid.UUID, file_id: uuid.UUID) -> BatchFile:
        row = self._file(batch_id, file_id); row.processing_status = BatchProcessingStatus.IGNORED
        self.session.commit(); self._synchronize(self.get(batch_id)); self.session.commit(); return row

    def cancel(self, batch_id: uuid.UUID) -> UploadBatch:
        batch = self.get(batch_id); batch.status = BatchStatus.CANCELLED; self.session.commit(); return batch

    def response(self, batch: UploadBatch, detail: bool = False):
        data = dict(id=batch.id, name=batch.name, category=batch.category, tags=batch.tags, note=batch.note, knowledge_base_id=batch.knowledge_base_id, status=batch.status,
            created_at=batch.created_at, updated_at=batch.updated_at, completed_at=batch.completed_at, **self._counts(batch.files))
        return BatchDetailResponse(**data, files=sorted(batch.files, key=lambda x: x.relative_path)) if detail else BatchResponse(**data)

    def synchronize_document(self, document_id: uuid.UUID) -> None:
        document = self.session.get(Document, document_id)
        if not document: return
        rows = list(self.session.scalars(select(BatchFile).where(BatchFile.document_id == document_id)))
        for row in rows:
            row.processing_status = processing_status(document)
            if row.processing_status == BatchProcessingStatus.FAILED:
                row.error_stage, row.error_code, row.error_message = "PROCESSING", document.error_code, document.error_message
        self.session.commit()
        for batch_id in {x.batch_id for x in rows}: self._synchronize(self.get(batch_id))
        self.session.commit()

    def _file(self, batch_id, file_id) -> BatchFile:
        row = self.session.scalar(select(BatchFile).where(BatchFile.id == file_id, BatchFile.batch_id == batch_id))
        if not row: raise AppError("BATCH_FILE_NOT_FOUND", "批次文件不存在", 404)
        return row

    @staticmethod
    def _relative_path(value: str) -> str:
        normalized = value.replace("\\", "/").strip()
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or ".." in path.parts or len(normalized) > 2048:
            raise AppError("INVALID_RELATIVE_PATH", "文件相对路径无效", 400)
        return path.as_posix()

    @staticmethod
    def _counts(files):
        return {"total_count": len(files), "indexed_count": sum(x.processing_status == BatchProcessingStatus.INDEXED for x in files),
            "processing_count": sum(x.processing_status in {BatchProcessingStatus.WAITING, BatchProcessingStatus.PROCESSING, BatchProcessingStatus.PARSED} for x in files),
            "duplicate_count": sum(x.upload_status == BatchUploadStatus.DUPLICATE for x in files),
            "failed_count": sum(x.upload_status == BatchUploadStatus.FAILED or x.processing_status == BatchProcessingStatus.FAILED for x in files),
            "pending_count": sum(x.upload_status == BatchUploadStatus.PENDING for x in files)}

    def _synchronize(self, batch):
        if batch.status == BatchStatus.CANCELLED: return
        for row in batch.files:
            if row.document: row.processing_status = processing_status(row.document)
        c = self._counts(batch.files)
        if c["failed_count"]: batch.status = BatchStatus.PARTIAL_FAILED
        elif batch.files and all(x.processing_status in {BatchProcessingStatus.INDEXED, BatchProcessingStatus.IGNORED} for x in batch.files):
            batch.status, batch.completed_at = BatchStatus.COMPLETED, datetime.now(UTC)
        elif any(x.upload_status in {BatchUploadStatus.PENDING, BatchUploadStatus.UPLOADING} for x in batch.files): batch.status = BatchStatus.UPLOADING
        elif batch.files: batch.status = BatchStatus.PROCESSING
