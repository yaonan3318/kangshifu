"""检索词典 ORM：管理员维护的同义词/缩写/专有名词，供查询扩展使用。"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DictionaryCategory(str, enum.Enum):
    SYNONYM = "SYNONYM"            # 同义词 / 近义词
    ABBREVIATION = "ABBREVIATION"  # 公司内部缩写、简称与全称
    PROPER_NOUN = "PROPER_NOUN"    # 专有名词、产品名
    CROSS_LANGUAGE = "CROSS_LANGUAGE"  # 中英文映射，如 气泡 -> bubble


class RetrievalDictionaryEntry(Base):
    __tablename__ = "retrieval_dictionary_entries"
    __table_args__ = (
        UniqueConstraint("category", "term", name="uq_retrieval_dictionary_category_term"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category: Mapped[DictionaryCategory] = mapped_column(
        Enum(DictionaryCategory, native_enum=False), index=True
    )
    term: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    expansions: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
