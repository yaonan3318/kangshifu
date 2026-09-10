"""文档业务服务：协调数据库元数据、磁盘文件和后台处理任务。"""

import uuid
from datetime import UTC, datetime

from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.errors import DocumentAlreadyProcessing, DocumentNotFound, DuplicateDocument
from app.errors import AppError
from app.models import (
    AclPermission, DEFAULT_KNOWLEDGE_BASE_ID, Department, Document, DocumentAcl, DocumentChunk,
    DocumentStatus, DocumentVisibility, JobStatus, JobType, KnowledgeBase, ProcessingJob, Role,
    SubjectType, Tag, User,
)
from app.ocr import TesseractOcrEngine
from app.parsers import ParserRegistry
from app.schemas.documents import DocumentFilters, DocumentUpdateRequest
from app.services.chunking import ChunkingConfig, chunk_blocks
from app.services.file_types import detect_allowed_type
from app.services.managed_storage import ManagedStorage
from app.services.permissions import PermissionResolver, require_manage, require_read


class DocumentService:
    """实现文档用例，并保证数据库记录和受管磁盘文件尽量保持一致。"""

    def __init__(self, session: Session, storage: ManagedStorage, user=None):
        self.session = session
        self.storage = storage
        self.resolver = PermissionResolver(session, user) if user is not None else None
        self.user = self.resolver.user if self.resolver else None

    def _check_read(self, document: Document) -> None:
        if self.resolver is not None:
            require_read(self.resolver, document)

    def _check_manage(self, document: Document) -> None:
        if self.resolver is not None:
            require_manage(self.resolver, document)

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
            previous = self.session.scalar(select(Document).where(
                Document.knowledge_base_id == target_base,
                Document.relative_path == staged.original_name,
                Document.deleted_at.is_(None),
            ).order_by(Document.version_number.desc()).limit(1))
            document = Document(
                id=uuid.uuid4(), original_name=staged.original_name,
                stored_path="", extension=file_type.extension, mime_type=file_type.mime_type,
                size_bytes=staged.size_bytes, sha256=staged.sha256, status=DocumentStatus.PENDING,
                knowledge_base_id=target_base, relative_path=staged.original_name,
                previous_version_id=previous.id if previous else None,
                version_number=(previous.version_number + 1) if previous else 1,
                owner_user_id=self.user.id if self.user else None,
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
        if self.resolver is not None:
            clauses.extend(self.resolver.visibility_clauses())
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
        self._check_read(document)
        return document

    def get_managed(self, document_id: uuid.UUID, include_deleted: bool = False) -> Document:
        """读取文档并要求 MANAGE 权限，供 ACL 读取等管理入口使用。"""
        document = self.get(document_id, include_deleted=include_deleted)
        self._check_manage(document)
        return document

    def delete(self, document_id: uuid.UUID, reason: str | None = None) -> None:
        document = self.get(document_id)
        self._check_manage(document)
        document.deleted_at = datetime.now(UTC)
        document.deleted_reason = reason.strip() if reason else None
        self.session.commit()

    def restore(self, document_id: uuid.UUID) -> Document:
        document = self.get(document_id, include_deleted=True)
        self._check_manage(document)
        if document.deleted_at is None:
            raise AppError("DOCUMENT_NOT_DELETED", "文档不在回收站中", 409)
        document.deleted_at = None
        document.deleted_reason = None
        self.session.commit()
        self.session.refresh(document)
        return document

    def purge(self, document_id: uuid.UUID) -> None:
        document = self.get(document_id, include_deleted=True)
        self._check_manage(document)
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
        self._check_manage(document)
        document.enabled = enabled
        self.session.commit()
        self.session.refresh(document)
        return document

    def update(self, document_id: uuid.UUID, body: DocumentUpdateRequest) -> Document:
        document = self.get(document_id)
        self._check_manage(document)
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
        # P2-6：作者/部门/主题/关联文档/有效期，为知识图谱与实体关系检索保留数据。
        if "author" in body.model_fields_set:
            document.author = body.author.strip() if body.author else None
        if "department_id" in body.model_fields_set:
            if body.department_id is not None and self.session.get(Department, body.department_id) is None:
                raise AppError("DEPARTMENT_NOT_FOUND", "部门不存在", 404)
            document.department_id = body.department_id
        if "topic" in body.model_fields_set:
            document.topic = body.topic.strip() if body.topic else None
        if body.related_document_ids is not None:
            document.related_document_ids = [str(item) for item in body.related_document_ids]
        if "valid_from" in body.model_fields_set:
            document.valid_from = body.valid_from
        if "valid_until" in body.model_fields_set:
            document.valid_until = body.valid_until
        self.session.commit()
        self.session.refresh(document)
        return self.get(document.id)

    def preview_chunks(
        self, document_id: uuid.UUID, config_override: dict | None = None, limit: int = 50,
    ) -> tuple[list, int, ChunkingConfig]:
        """解析文档并按切片策略预览结果，不写入数据库。"""
        document = self.get(document_id)
        self._check_manage(document)
        parser = ParserRegistry(TesseractOcrEngine()).get(document.extension)
        blocks = parser.parse(self.storage.resolve(document.stored_path))
        knowledge_base = self.session.get(KnowledgeBase, document.knowledge_base_id)
        base = ChunkingConfig.from_dict(knowledge_base.chunking_config if knowledge_base else None)
        config = ChunkingConfig.from_dict(config_override) if config_override else base
        chunks = chunk_blocks(blocks, config)
        return chunks[:limit], len(chunks), config

    def versions(self, document_id: uuid.UUID) -> list[Document]:
        """返回版本链；入口要求可读，链上每个版本再按当前用户重新鉴权。

        遍历链条时使用全部子节点，确保中间版本不可读时仍能找到后续可读版本；
        但最终返回值只包含当前用户可读的版本，避免通过版本 API 越权查看。
        """
        document = self.get(document_id, include_deleted=True)
        root_id = document.id
        # 沿 previous_version_id 向上找根版本，不在此处鉴权，交给最终过滤。
        seen: set[uuid.UUID] = {document.id}
        current = document
        while current.previous_version_id and current.previous_version_id not in seen:
            parent = self.session.get(Document, current.previous_version_id)
            if parent is None:
                break
            seen.add(parent.id)
            current = parent
            root_id = parent.id

        def readable(candidate: Document) -> bool:
            return self.resolver is None or self.resolver.can_read(candidate)

        values: list[Document] = []
        root = self.session.get(Document, root_id)
        if root is not None and readable(root):
            values.append(root)
        frontier = [root_id]
        while frontier:
            children = list(self.session.scalars(select(Document).where(Document.previous_version_id.in_(frontier))))
            values.extend(child for child in children if readable(child))
            frontier = [item.id for item in children]
        return sorted({item.id: item for item in values}.values(), key=lambda item: item.version_number, reverse=True)

    def chunk_count(self, document_id: uuid.UUID) -> int:
        return self.session.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == document_id)) or 0

    def _validate_acl(self, acl: list[dict]) -> list[tuple[SubjectType, uuid.UUID, AclPermission]]:
        """校验授权对象存在且启用，并按 (类型, 对象) 去重后保留最高权限。"""
        merged: dict[tuple[SubjectType, uuid.UUID], AclPermission] = {}
        order: list[tuple[SubjectType, uuid.UUID]] = []
        for entry in acl:
            try:
                subject_type = SubjectType(entry.get("subject_type"))
            except ValueError as exc:
                raise AppError("ACL_SUBJECT_TYPE_INVALID", "授权对象类型不正确", 422) from exc
            subject_id = uuid.UUID(str(entry.get("subject_id")))
            permission = AclPermission(entry.get("permission") or "READ")
            model = {SubjectType.DEPARTMENT: Department, SubjectType.ROLE: Role, SubjectType.USER: User}[subject_type]
            subject = self.session.get(model, subject_id)
            if subject is None:
                raise AppError("ACL_SUBJECT_NOT_FOUND", "授权对象不存在", 404, {"subject_id": str(subject_id)})
            if not subject.enabled:
                raise AppError("ACL_SUBJECT_DISABLED", "不能授权给已停用的对象", 409, {"subject_id": str(subject_id)})
            key = (subject_type, subject_id)
            if key not in merged:
                order.append(key)
                merged[key] = permission
            elif permission == AclPermission.MANAGE:
                merged[key] = AclPermission.MANAGE
        return [(subject_type, subject_id, merged[(subject_type, subject_id)]) for subject_type, subject_id in order]

    def set_access(
        self, document_id: uuid.UUID,
        visibility: DocumentVisibility | None = None,
        acl: list[dict] | None = None,
    ) -> Document:
        """设置文档可见级别与访问控制表；只允许上传人、管理员或被授予 MANAGE 的用户。"""
        document = self.get(document_id)
        self._check_manage(document)
        entries = self._validate_acl(acl) if acl is not None else None
        if visibility is not None:
            document.visibility = visibility
        if entries is not None:
            self.session.execute(
                delete(DocumentAcl).where(DocumentAcl.document_id == document.id)
            )
            for subject_type, subject_id, permission in entries:
                self.session.add(DocumentAcl(
                    document_id=document.id, subject_type=subject_type,
                    subject_id=subject_id, permission=permission,
                ))
        self.session.commit()
        self.session.refresh(document)
        return self.get(document.id)

    def set_external_policy(
        self, document_id: uuid.UUID, sensitivity_level: str, external_llm_allowed: bool,
    ) -> Document:
        """设置敏感级别与外部模型外发策略；不影响本地千问。"""
        document = self.get(document_id)
        self._check_manage(document)
        document.sensitivity_level = sensitivity_level
        document.external_llm_allowed = external_llm_allowed
        self.session.commit()
        self.session.refresh(document)
        return self.get(document.id)

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

    def reprocess(self, document_id: uuid.UUID, confirm_overwrite: bool = False) -> Document:
        document = self.get(document_id)
        self._check_manage(document)
        edited = self.session.scalar(select(DocumentChunk.id).where(
            DocumentChunk.document_id == document_id, DocumentChunk.manually_edited.is_(True)
        ).limit(1))
        if edited and not confirm_overwrite:
            raise AppError("MANUAL_CHUNKS_WOULD_BE_LOST", "重新处理会覆盖人工修改的片段，请确认后继续", 409)
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
