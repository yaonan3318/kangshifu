"""所有检索入口共享的资料可见性 SQL 条件。"""

from sqlalchemy import exists, select
from sqlalchemy.orm import aliased

from app.models import Document, DocumentChunk, DocumentStatus, KnowledgeBase


def active_retrieval_clauses():
    """排除停用、删除、未就绪、知识库停用和已有成功新版本的资料。"""
    newer = aliased(Document)
    has_newer_ready_version = exists(select(newer.id).where(
        newer.previous_version_id == Document.id,
        newer.status == DocumentStatus.READY,
        newer.enabled.is_(True),
        newer.deleted_at.is_(None),
    ))
    return [
        Document.status == DocumentStatus.READY,
        Document.enabled.is_(True),
        Document.deleted_at.is_(None),
        KnowledgeBase.enabled.is_(True),
        DocumentChunk.enabled.is_(True),
        ~has_newer_ready_version,
    ]
