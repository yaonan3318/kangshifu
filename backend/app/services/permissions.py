"""文档可见性与管理权限解析：检索 SQL 层过滤与读写入口校验统一复用。"""

import uuid

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AclPermission, Department, Document, DocumentAcl, DocumentVisibility, Role, SubjectType, User

PRIVATE = "PRIVATE"
COMPANY = "COMPANY"


class PermissionResolver:
    """基于当前用户解析文档可见性；检索层把结果拼进 SQL，单条读取走 can_read。"""

    def __init__(self, session: Session, user: User | None):
        self.session = session
        self.user = user
        self._ancestor_department_ids: list[uuid.UUID] | None = None
        self._role_ids: list[uuid.UUID] | None = None

    @property
    def is_super_admin(self) -> bool:
        return bool(self.user and self.user.is_super_admin)

    @property
    def department_ids(self) -> list[uuid.UUID]:
        """用户所在部门及其全部上级部门；停用部门不再授予访问权限。"""
        if self._ancestor_department_ids is None:
            result: list[uuid.UUID] = []
            current_id = self.user.department_id if self.user else None
            seen: set[uuid.UUID] = set()
            while current_id and current_id not in seen:
                seen.add(current_id)
                row = self.session.get(Department, current_id)
                if row is not None and row.enabled:
                    result.append(current_id)
                current_id = row.parent_id if row else None
            self._ancestor_department_ids = result
        return self._ancestor_department_ids

    @property
    def role_ids(self) -> list[uuid.UUID]:
        """仅启用中的角色参与权限判断；停用角色保留历史 ACL 但不生效。"""
        if self._role_ids is None:
            self._role_ids = [role.id for role in (self.user.roles if self.user else []) if role.enabled]
        return self._role_ids

    def visibility_clauses(self) -> list:
        """返回用于 Document 查询的可见性条件；管理员或不带用户时不做限制。"""
        if self.user is None or self.user.is_super_admin:
            return []
        acl = DocumentAcl
        clauses = or_(
            Document.visibility == DocumentVisibility.COMPANY,
            (Document.visibility == DocumentVisibility.PRIVATE) & (Document.owner_user_id == self.user.id),
            exists(select(acl.id).where(
                acl.document_id == Document.id, acl.subject_type == SubjectType.DEPARTMENT,
                acl.subject_id.in_(self.department_ids),
            )),
            exists(select(acl.id).where(
                acl.document_id == Document.id, acl.subject_type == SubjectType.ROLE,
                acl.subject_id.in_(self.role_ids),
            )),
            exists(select(acl.id).where(
                acl.document_id == Document.id, acl.subject_type == SubjectType.USER,
                acl.subject_id == self.user.id,
            )),
        )
        return [clauses]

    def can_read(self, document: Document) -> bool:
        if self.user is None or self.user.is_super_admin:
            return True
        if document.visibility == DocumentVisibility.COMPANY:
            return True
        if document.visibility == DocumentVisibility.PRIVATE:
            return document.owner_user_id == self.user.id
        document_id = document.id
        query = select(DocumentAcl.id).where(DocumentAcl.document_id == document_id)
        if document.visibility == DocumentVisibility.DEPARTMENT:
            query = query.where(DocumentAcl.subject_type == SubjectType.DEPARTMENT, DocumentAcl.subject_id.in_(self.department_ids))
        elif document.visibility == DocumentVisibility.ROLE:
            query = query.where(DocumentAcl.subject_type == SubjectType.ROLE, DocumentAcl.subject_id.in_(self.role_ids))
        elif document.visibility == DocumentVisibility.USER:
            query = query.where(DocumentAcl.subject_type == SubjectType.USER, DocumentAcl.subject_id == self.user.id)
        else:
            return False
        return self.session.scalar(query) is not None

    def can_manage(self, document: Document) -> bool:
        if self.user is None or self.user.is_super_admin:
            return True
        if document.owner_user_id == self.user.id:
            return True
        granted = self.session.scalar(select(DocumentAcl.id).where(
            DocumentAcl.document_id == document.id,
            DocumentAcl.permission == AclPermission.MANAGE,
            or_(
                (DocumentAcl.subject_type == SubjectType.USER) & (DocumentAcl.subject_id == self.user.id),
                (DocumentAcl.subject_type == SubjectType.DEPARTMENT) & DocumentAcl.subject_id.in_(self.department_ids),
                (DocumentAcl.subject_type == SubjectType.ROLE) & DocumentAcl.subject_id.in_(self.role_ids),
            ),
        ))
        return granted is not None


def require_user(user: User | None) -> User:
    if user is None:
        raise AppError("AUTH_REQUIRED", "请先登录", 401)
    if not user.enabled:
        raise AppError("ACCOUNT_DISABLED", "账号已被停用", 403)
    return user


def require_read(resolver: PermissionResolver, document: Document) -> None:
    if not resolver.can_read(document):
        raise AppError("DOCUMENT_FORBIDDEN", "没有权限查看该资料", 403)


def require_manage(resolver: PermissionResolver, document: Document) -> None:
    if not resolver.can_manage(document):
        raise AppError("DOCUMENT_MANAGE_FORBIDDEN", "没有权限管理该资料", 403)


def require_admin(user: User | None) -> User:
    current = require_user(user)
    if not current.is_super_admin:
        raise AppError("ADMIN_REQUIRED", "需要管理员权限", 403)
    return current
