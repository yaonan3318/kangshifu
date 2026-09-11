"""助手 ORM：可配置角色的知识助手，绑定模型、知识库、提示词与启用状态。"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, func, Table, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

DEFAULT_ASSISTANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


assistant_knowledge_bases = Table(
    "assistant_knowledge_bases",
    Base.metadata,
    Column("assistant_id", UUID(as_uuid=True), ForeignKey("assistants.id", ondelete="CASCADE"), primary_key=True),
    Column("knowledge_base_id", UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True),
)


class Assistant(Base):
    """助手配置；knowledge_bases 为空表示使用全部启用中的知识库。"""
    __tablename__ = "assistants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    avatar: Mapped[str] = mapped_column(String(16), default="康")
    welcome_message: Mapped[str | None] = mapped_column(Text)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    model_provider: Mapped[str] = mapped_column(String(32), default="ollama")
    model_name: Mapped[str | None] = mapped_column(String(255))
    use_deepseek_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    default_deepseek_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # 运行策略由管理员在助手配置中确定，问答用户不能按请求覆盖。
    deepseek_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    harness_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    harness_context: Mapped[str | None] = mapped_column(String(255))
    harness_namespace: Mapped[str] = mapped_column(String(255), default="default")
    retrieval_limit: Mapped[int] = mapped_column(Integer, default=6)
    temperature: Mapped[float] = mapped_column(Float, default=0.2)
    recommended_questions: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    # P2-3 角色增强：默认答案模板、联网开关、无答案策略，以及欢迎页“能做/不能做”。
    answer_template: Mapped[str] = mapped_column(String(32), default="AUTO", server_default="AUTO")
    internet_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    no_answer_policy: Mapped[str] = mapped_column(String(16), default="SUGGEST", server_default="SUGGEST")
    capabilities: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    limitations: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    # P2-3：知识库范围语义。True=全部启用知识库；False 且无绑定=尚未配置（不可检索）。
    allow_all_knowledge_bases: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    # P2-4：助手可绑定一个已发布的 Chatflow；为空时使用内置默认流程。
    chatflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chatflows.id", ondelete="SET NULL"), nullable=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    knowledge_bases: Mapped[list["KnowledgeBase"]] = relationship(secondary=assistant_knowledge_bases)


from app.models.knowledge_base import KnowledgeBase  # noqa: E402
