"""检索词典服务：管理员维护同义词/缩写/专有名词，供查询扩展与拼写纠正使用。

词条来自数据库，不在代码里写死；加载时构建双向映射，因此简称与全称可以互相扩展。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import DictionaryCategory, RetrievalDictionaryEntry


def load_expansions(session: Session) -> dict[str, list[str]]:
    """加载启用词条并构建双向扩展表；单个词条最多扩展到整组词。"""
    entries = session.scalars(
        select(RetrievalDictionaryEntry).where(RetrievalDictionaryEntry.enabled.is_(True))
    ).all()
    mapping: dict[str, list[str]] = {}
    for entry in entries:
        term = (entry.term or "").strip().lower()
        expansions = [str(item).strip().lower() for item in (entry.expansions or []) if str(item).strip()]
        if not term:
            continue
        group = list(dict.fromkeys([term, *expansions]))
        for member in group:
            mapping[member] = list(dict.fromkeys([*mapping.get(member, []), *[item for item in group if item != member]]))
    return mapping


class DictionaryService:
    def __init__(self, session: Session):
        self.session = session

    def list(self, category: str | None = None, enabled: bool | None = None) -> list[RetrievalDictionaryEntry]:
        statement = select(RetrievalDictionaryEntry)
        if category:
            statement = statement.where(RetrievalDictionaryEntry.category == self._category(category))
        if enabled is not None:
            statement = statement.where(RetrievalDictionaryEntry.enabled.is_(enabled))
        return list(self.session.scalars(statement.order_by(RetrievalDictionaryEntry.category, RetrievalDictionaryEntry.term)))

    def get(self, entry_id: uuid.UUID) -> RetrievalDictionaryEntry:
        value = self.session.get(RetrievalDictionaryEntry, entry_id)
        if value is None:
            raise AppError("DICTIONARY_ENTRY_NOT_FOUND", "词典词条不存在", 404)
        return value

    def create(self, category: str, term: str, expansions: list[str], enabled: bool = True) -> RetrievalDictionaryEntry:
        cleaned_term = term.strip().lower()
        if not cleaned_term:
            raise AppError("DICTIONARY_TERM_REQUIRED", "词条不能为空", 422)
        value = RetrievalDictionaryEntry(
            category=self._category(category), term=cleaned_term,
            expansions=self._clean_expansions(expansions), enabled=enabled,
        )
        self.session.add(value)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise AppError("DICTIONARY_TERM_EXISTS", "同类别下已存在该词条", 409) from None
        self.session.refresh(value)
        return value

    def update(
        self, entry_id: uuid.UUID, *, term: str | None = None,
        expansions: list[str] | None = None, enabled: bool | None = None,
    ) -> RetrievalDictionaryEntry:
        value = self.get(entry_id)
        if term is not None:
            cleaned = term.strip().lower()
            if not cleaned:
                raise AppError("DICTIONARY_TERM_REQUIRED", "词条不能为空", 422)
            value.term = cleaned
        if expansions is not None:
            value.expansions = self._clean_expansions(expansions)
        if enabled is not None:
            value.enabled = enabled
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise AppError("DICTIONARY_TERM_EXISTS", "同类别下已存在该词条", 409) from None
        self.session.refresh(value)
        return value

    def delete(self, entry_id: uuid.UUID) -> None:
        self.session.delete(self.get(entry_id))
        self.session.commit()

    @staticmethod
    def _category(value: str) -> DictionaryCategory:
        try:
            return DictionaryCategory(value)
        except ValueError as exc:
            raise AppError("DICTIONARY_CATEGORY_INVALID", "词典类别不正确", 422) from exc

    @staticmethod
    def _clean_expansions(expansions: list[str]) -> list[str]:
        cleaned = [str(item).strip().lower() for item in expansions if str(item).strip()]
        return list(dict.fromkeys(cleaned))
