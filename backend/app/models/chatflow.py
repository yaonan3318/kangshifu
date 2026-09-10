"""轻量 Chatflow ORM：固定画布的流程草稿、发布版本与助手绑定。

第一版不做自由拖拽，节点顺序与分支由图的 next / branches 决定；
草稿与发布版本分开保存，支持回滚历史版本。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Chatflow(Base):
    __tablename__ = "chatflows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    # 草稿与已发布图分开保存；published_version=0 表示尚未发布。
    draft_graph: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    published_graph: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    published_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    versions: Mapped[list["ChatflowVersion"]] = relationship(
        back_populates="chatflow", cascade="all, delete-orphan",
    )


class ChatflowVersion(Base):
    __tablename__ = "chatflow_versions"
    __table_args__ = (
        UniqueConstraint("chatflow_id", "version", name="uq_chatflow_versions_chatflow_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chatflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chatflows.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    graph: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    chatflow: Mapped[Chatflow] = relationship(back_populates="versions")
