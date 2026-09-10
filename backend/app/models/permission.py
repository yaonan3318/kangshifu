"""功能级 RBAC ORM：固定权限码目录与角色-权限绑定。

权限码是稳定契约（前端菜单、后端逐接口校验共用）；角色可绑定多个权限，
用户通过启用角色获得权限并集。该模型与文档 ACL 相互独立、同时生效。
"""

from sqlalchemy import Column, ForeignKey, Integer, String, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Permission(Base):
    """固定权限码目录；迁移负责幂等写入，代码不再增删。"""

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_code", String(64), ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True),
)
