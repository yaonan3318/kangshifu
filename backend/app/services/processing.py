import logging
from datetime import UTC, datetime, timedelta

import pymupdf
import pytesseract
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Document, DocumentChunk, DocumentStatus, JobStatus, JobType, ProcessingJob
from app.ocr import TesseractOcrEngine
from app.parsers import ParserRegistry
from app.services.chunking import chunk_blocks
from app.services.embeddings import EmbeddingService
from app.services.keywords import keyword_text
from app.services.managed_storage import ManagedStorage

logger = logging.getLogger(__name__)


class ProcessingService:
    def __init__(self, session: Session, settings: Settings):
        self.session = session
        self.settings = settings
        self.storage = ManagedStorage(settings)
        self.registry = ParserRegistry(TesseractOcrEngine())
        self.embeddings = EmbeddingService(settings)

    def recover_stale_jobs(self) -> int:
        cutoff = datetime.now(UTC) - timedelta(minutes=self.settings.worker_stale_minutes)
        jobs = list(self.session.scalars(select(ProcessingJob).where(ProcessingJob.status == JobStatus.RUNNING, ProcessingJob.started_at < cutoff)))
        for job in jobs:
            job.status = JobStatus.QUEUED
            job.started_at = None
            job.error_code = "WORKER_INTERRUPTED"
            job.error_message = "后台处理被中断，已重新排队"
            if job.document.status != DocumentStatus.DELETING:
                job.document.status = DocumentStatus.PENDING if job.job_type == JobType.PARSE else DocumentStatus.PARSED
        self.session.commit()
        return len(jobs)

    def claim_next_job(self) -> ProcessingJob | None:
        job = self.session.scalar(
            select(ProcessingJob).where(ProcessingJob.status == JobStatus.QUEUED)
            .order_by(ProcessingJob.created_at, ProcessingJob.id).with_for_update(skip_locked=True).limit(1)
        )
        if not job:
            self.session.rollback()
            return None
        if job.document.status == DocumentStatus.DELETING:
            job.status = JobStatus.FAILED
            job.error_code = "DOCUMENT_DELETING"
            job.error_message = "文档正在删除"
            job.finished_at = datetime.now(UTC)
            self.session.commit()
            return None
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.started_at = datetime.now(UTC)
        job.error_code = None
        job.error_message = None
        self.session.commit()
        return job

    def process(self, job: ProcessingJob) -> None:
        try:
            document = self.session.get(Document, job.document_id)
            if not document or document.status == DocumentStatus.DELETING:
                return
            if job.job_type == JobType.INDEX:
                self._index(document, job)
                return
            self._parse(document, job)
        except Exception as exc:
            self.session.rollback()
            self._mark_failed(job.id, exc)

    def _parse(self, document: Document, job: ProcessingJob) -> None:
        document.status = DocumentStatus.PARSING
        document.error_code = None
        document.error_message = None
        self.session.commit()

        parser = self.registry.get(document.extension)
        blocks = parser.parse(self.storage.resolve(document.stored_path))
        if not blocks:
            raise ValueError("EMPTY_CONTENT")

        document.status = DocumentStatus.CHUNKING
        self.session.commit()
        chunks = chunk_blocks(blocks)
        if not chunks:
            raise ValueError("EMPTY_CONTENT")

        self.session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
        for sequence, chunk in enumerate(chunks, start=1):
            self.session.add(DocumentChunk(
                document_id=document.id, sequence_number=sequence, content=chunk.content,
                page_start=chunk.page_start, page_end=chunk.page_end, slide_number=chunk.slide_number,
                sheet_name=chunk.sheet_name, row_start=chunk.row_start, row_end=chunk.row_end,
                section_path=chunk.section_path, ocr_confidence=chunk.ocr_confidence,
            ))
        document.status = DocumentStatus.PARSED
        document.parser_name = parser.name
        document.parser_version = parser.version
        job = self.session.get(ProcessingJob, job.id)
        job.status = JobStatus.SUCCEEDED
        job.finished_at = datetime.now(UTC)
        document.jobs.append(ProcessingJob(job_type=JobType.INDEX, status=JobStatus.QUEUED))
        self.session.commit()

    def _index(self, document: Document, job: ProcessingJob) -> None:
        chunks = list(self.session.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == document.id).order_by(DocumentChunk.sequence_number)
        ))
        if not chunks:
            raise ValueError("EMPTY_CONTENT")

        document.status = DocumentStatus.EMBEDDING
        document.error_code = None
        document.error_message = None
        self.session.commit()
        vectors = self.embeddings.encode_documents([chunk.content for chunk in chunks])

        document.status = DocumentStatus.INDEXING
        self.session.commit()
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk.embedding = vector
            source_text = " ".join([document.original_name, *chunk.section_path, chunk.content])
            self.session.execute(
                update(DocumentChunk).where(DocumentChunk.id == chunk.id).values(
                    search_vector=func.to_tsvector("simple", keyword_text(source_text))
                )
            )
        document.embedding_model = self.settings.embedding_model
        document.embedding_version = "1"
        document.status = DocumentStatus.READY
        job = self.session.get(ProcessingJob, job.id)
        job.status = JobStatus.SUCCEEDED
        job.finished_at = datetime.now(UTC)
        self.session.commit()

    def _mark_failed(self, job_id, exc: Exception) -> None:
        job = self.session.get(ProcessingJob, job_id)
        if not job:
            return
        if job.job_type == JobType.INDEX:
            code, message, status = "INDEX_FAILED", "文档索引失败，请查看本地日志后重新处理", DocumentStatus.INDEX_FAILED
        else:
            code, message, status = self._classify_error(exc)
        job.status = JobStatus.FAILED
        job.error_code = code
        job.error_message = message
        job.finished_at = datetime.now(UTC)
        job.document.status = status
        job.document.error_code = code
        job.document.error_message = message
        self.session.commit()
        logger.exception("Document processing failed: %s", job.document_id, exc_info=exc)

    @staticmethod
    def _classify_error(exc: Exception) -> tuple[str, str, DocumentStatus]:
        if isinstance(exc, pytesseract.TesseractNotFoundError):
            return "OCR_NOT_INSTALLED", "未找到本地 OCR 程序，请重新运行安装脚本", DocumentStatus.OCR_FAILED
        if isinstance(exc, pytesseract.TesseractError):
            return "OCR_FAILED", "OCR 识别失败，可以重新处理", DocumentStatus.OCR_FAILED
        if isinstance(exc, pymupdf.FileDataError):
            return "CORRUPT_PDF", "PDF 文件已损坏，无法解析", DocumentStatus.PARSE_FAILED
        if str(exc) == "ENCRYPTED_PDF":
            return "ENCRYPTED_PDF", "PDF 已加密，请解密后重新上传", DocumentStatus.PARSE_FAILED
        if str(exc) == "EMPTY_CONTENT":
            return "EMPTY_CONTENT", "文档未提取到有效文字", DocumentStatus.PARSE_FAILED
        return "PARSE_FAILED", "文档解析失败，请查看本地日志", DocumentStatus.PARSE_FAILED
