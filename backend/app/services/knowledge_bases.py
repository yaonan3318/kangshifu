"""知识库业务：管理资料域并保护最后一个可用知识库。"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Document, KnowledgeBase


class KnowledgeBaseService:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[tuple[KnowledgeBase, int]]:
        count = func.count(Document.id).filter(Document.deleted_at.is_(None))
        return list(self.session.execute(
            select(KnowledgeBase, count).outerjoin(Document).group_by(KnowledgeBase.id)
            .order_by(KnowledgeBase.created_at, KnowledgeBase.id)
        ).all())

    def get(self, knowledge_base_id: uuid.UUID, require_enabled: bool = False) -> KnowledgeBase:
        clauses = [KnowledgeBase.id == knowledge_base_id]
        if require_enabled:
            clauses.append(KnowledgeBase.enabled.is_(True))
        value = self.session.scalar(select(KnowledgeBase).where(*clauses))
        if not value:
            raise AppError("KNOWLEDGE_BASE_NOT_FOUND", "知识库不存在或已停用", 404)
        return value

    def create(self, name: str, description: str | None, chunking_config: dict | None = None) -> KnowledgeBase:
        value = KnowledgeBase(
            name=name.strip(), description=description.strip() if description else None,
            chunking_config=chunking_config or {},
        )
        self.session.add(value)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise AppError("KNOWLEDGE_BASE_NAME_EXISTS", "知识库名称已经存在", 409) from None
        self.session.refresh(value)
        return value

    def update(
        self, knowledge_base_id: uuid.UUID, name: str | None, description: str | None,
        chunking_config: dict | None = None, chunking_config_set: bool = False,
    ) -> KnowledgeBase:
        value = self.get(knowledge_base_id)
        if name is not None:
            value.name = name.strip()
        if description is not None:
            value.description = description.strip() or None
        if chunking_config_set:
            value.chunking_config = chunking_config or {}
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise AppError("KNOWLEDGE_BASE_NAME_EXISTS", "知识库名称已经存在", 409) from None
        self.session.refresh(value)
        return value

    def set_enabled(self, knowledge_base_id: uuid.UUID, enabled: bool) -> KnowledgeBase:
        value = self.get(knowledge_base_id)
        if not enabled and value.enabled:
            active = self.session.scalar(select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.enabled.is_(True))) or 0
            if active <= 1:
                raise AppError("LAST_KNOWLEDGE_BASE", "至少需要保留一个启用的知识库", 409)
        value.enabled = enabled
        self.session.commit()
        self.session.refresh(value)
        return value
