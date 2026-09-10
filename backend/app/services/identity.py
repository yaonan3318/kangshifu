"""用户、部门与角色管理业务逻辑。

所有写操作只允许超级管理员调用（由 API 层 ``require_admin`` 保证）；
这里集中处理唯一性、启停保护、循环父子关系与登录会话撤销。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.errors import AppError
from app.models import (
    AuthSession, Department, DocumentAcl, Permission, Role, SubjectType, User,
    role_permissions, user_roles,
)
from app.services.auth import hash_password
from app.services.rbac import PERMISSION_CODES


# ---------------------------------------------------------------- 用户

def _role_briefs(user: User) -> list[dict]:
    return [{"id": role.id, "name": role.name} for role in sorted(user.roles, key=lambda item: item.name)]


def user_payload(user: User) -> dict:
    return {
        "id": user.id, "username": user.username, "display_name": user.display_name,
        "department_id": user.department_id,
        "department_name": user.department.name if user.department else None,
        "roles": _role_briefs(user), "is_super_admin": user.is_super_admin,
        "enabled": user.enabled, "last_login_at": user.last_login_at,
        "created_at": user.created_at, "updated_at": user.updated_at,
    }


def load_user(session: Session, user_id: uuid.UUID) -> User:
    user = session.scalar(
        select(User).where(User.id == user_id)
        .options(selectinload(User.roles), selectinload(User.department))
    )
    if user is None:
        raise AppError("USER_NOT_FOUND", "用户不存在", 404)
    return user


def list_users(
    session: Session, search: str | None = None, department_id: uuid.UUID | None = None,
    role_id: uuid.UUID | None = None, enabled: bool | None = None,
    page: int = 1, page_size: int = 20,
) -> tuple[list[User], int]:
    statement = select(User).options(selectinload(User.roles), selectinload(User.department))
    filters = []
    if search:
        keyword = search.strip()
        filters.append(or_(
            User.username.ilike(f"%{keyword}%"),
            User.display_name.ilike(f"%{keyword}%"),
        ))
    if department_id is not None:
        filters.append(User.department_id == department_id)
    if role_id is not None:
        filters.append(User.roles.any(Role.id == role_id))
    if enabled is not None:
        filters.append(User.enabled.is_(enabled))
    total = session.scalar(select(func.count()).select_from(User).where(*filters)) or 0
    rows = list(session.scalars(
        statement.where(*filters).order_by(User.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ))
    return rows, total


def validate_roles(session: Session, role_ids: list[uuid.UUID]) -> list[Role]:
    ids = list(dict.fromkeys(role_ids))
    if not ids:
        return []
    roles = list(session.scalars(select(Role).where(Role.id.in_(ids))).all())
    missing = [item for item in ids if item not in {role.id for role in roles}]
    if missing:
        raise AppError("ROLE_NOT_FOUND", "指定的角色不存在", 404, {"ids": [str(item) for item in missing]})
    return roles


def validate_department(session: Session, department_id: uuid.UUID | None, require_enabled: bool = True) -> Department | None:
    if department_id is None:
        return None
    department = session.get(Department, department_id)
    if department is None:
        raise AppError("DEPARTMENT_NOT_FOUND", "部门不存在", 404)
    if require_enabled and not department.enabled:
        raise AppError("DEPARTMENT_DISABLED", "不能选择已停用的部门", 409)
    return department


def create_user(
    session: Session, *, username: str, display_name: str, password: str,
    department_id: uuid.UUID | None, role_ids: list[uuid.UUID],
    is_super_admin: bool, enabled: bool,
) -> User:
    cleaned = username.strip()
    if not cleaned:
        raise AppError("USERNAME_REQUIRED", "用户名不能为空", 422)
    if session.scalar(select(User).where(User.username == cleaned)) is not None:
        raise AppError("USERNAME_EXISTS", "用户名已存在", 409)
    validate_department(session, department_id, require_enabled=True)
    roles = validate_roles(session, role_ids)
    user = User(
        username=cleaned, display_name=display_name.strip(),
        password_hash=hash_password(password), department_id=department_id,
        enabled=enabled, is_super_admin=is_super_admin,
    )
    user.roles.extend(roles)
    session.add(user)
    session.commit()
    return load_user(session, user.id)


def update_user(
    session: Session, user_id: uuid.UUID, *, current: User, display_name: str | None = None,
    department_id: uuid.UUID | None = None, department_set: bool = False,
    role_ids: list[uuid.UUID] | None = None, is_super_admin: bool | None = None,
    enabled: bool | None = None,
) -> User:
    target = load_user(session, user_id)
    if display_name is not None:
        target.display_name = display_name.strip()
    if department_set:
        if department_id is not None:
            validate_department(session, department_id, require_enabled=True)
        target.department_id = department_id
    if role_ids is not None:
        target.roles = validate_roles(session, role_ids)
    if is_super_admin is not None and target.id != current.id:
        if not is_super_admin and target.is_super_admin and target.enabled:
            _guard_last_super_admin(session, target)
        target.is_super_admin = is_super_admin
    if enabled is not None:
        _apply_enabled(session, target, enabled, current)
    session.commit()
    return load_user(session, user_id)


def _enabled_super_admin_count(session: Session, exclude_id: uuid.UUID | None = None) -> int:
    filters = [User.is_super_admin.is_(True), User.enabled.is_(True)]
    if exclude_id is not None:
        filters.append(User.id != exclude_id)
    return session.scalar(select(func.count()).select_from(User).where(*filters)) or 0


def _guard_last_super_admin(session: Session, target: User) -> None:
    if _enabled_super_admin_count(session, exclude_id=target.id) == 0:
        raise AppError("LAST_SUPER_ADMIN", "不能停用系统中唯一启用的超级管理员", 409)


def _apply_enabled(session: Session, target: User, enabled: bool, current: User) -> None:
    if enabled:
        target.enabled = True
        return
    if not target.enabled:
        return
    if target.is_super_admin:
        _guard_last_super_admin(session, target)
    if target.id == current.id and target.is_super_admin and _enabled_super_admin_count(session, exclude_id=target.id) == 0:
        raise AppError("CANNOT_DISABLE_SELF", "不能停用自己，除非系统还有其他启用的超级管理员", 409)
    target.enabled = False
    revoke_user_sessions(session, target.id)


def revoke_user_sessions(session: Session, user_id: uuid.UUID) -> int:
    result = session.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    return result.rowcount or 0


def reset_password(session: Session, user_id: uuid.UUID, new_password: str) -> User:
    target = load_user(session, user_id)
    target.password_hash = hash_password(new_password)
    revoke_user_sessions(session, target.id)
    session.commit()
    return target


def set_enabled(session: Session, user_id: uuid.UUID, enabled: bool, current: User) -> User:
    target = load_user(session, user_id)
    _apply_enabled(session, target, enabled, current)
    session.commit()
    return load_user(session, user_id)


# ---------------------------------------------------------------- 部门

def department_user_count(session: Session, department_id: uuid.UUID) -> int:
    return session.scalar(
        select(func.count()).select_from(User).where(User.department_id == department_id)
    ) or 0


def department_payload(session: Session, department: Department) -> dict:
    return {
        "id": department.id, "name": department.name, "parent_id": department.parent_id,
        "enabled": department.enabled, "created_at": department.created_at,
        "updated_at": department.updated_at,
        "user_count": department_user_count(session, department.id),
    }


def department_tree(session: Session) -> list[dict]:
    rows = list(session.scalars(select(Department).order_by(Department.name)))
    payloads = {row.id: {**department_payload(session, row), "children": []} for row in rows}
    roots: list[dict] = []
    for row in rows:
        node = payloads[row.id]
        parent = payloads.get(row.parent_id) if row.parent_id else None
        if parent is not None:
            parent["children"].append(node)
        else:
            roots.append(node)
    return roots


def load_department(session: Session, department_id: uuid.UUID) -> Department:
    department = session.get(Department, department_id)
    if department is None:
        raise AppError("DEPARTMENT_NOT_FOUND", "部门不存在", 404)
    return department


def _name_taken(session: Session, name: str, exclude_id: uuid.UUID | None = None) -> bool:
    filters = [Department.name == name]
    if exclude_id is not None:
        filters.append(Department.id != exclude_id)
    return session.scalar(select(Department.id).where(*filters)) is not None


def create_department(session: Session, *, name: str, parent_id: uuid.UUID | None, enabled: bool) -> Department:
    cleaned = name.strip()
    if not cleaned:
        raise AppError("DEPARTMENT_NAME_REQUIRED", "部门名称不能为空", 422)
    if _name_taken(session, cleaned):
        raise AppError("DEPARTMENT_NAME_EXISTS", "部门名称已存在", 409)
    if parent_id is not None:
        parent = load_department(session, parent_id)
        if not parent.enabled:
            raise AppError("DEPARTMENT_DISABLED", "不能在已停用部门下创建子部门", 409)
    department = Department(name=cleaned, parent_id=parent_id, enabled=enabled)
    session.add(department)
    session.commit()
    session.refresh(department)
    return department


def _would_cycle(session: Session, department_id: uuid.UUID, parent_id: uuid.UUID | None) -> bool:
    current = parent_id
    seen: set[uuid.UUID] = set()
    while current is not None and current not in seen:
        if current == department_id:
            return True
        seen.add(current)
        row = session.get(Department, current)
        current = row.parent_id if row else None
    return False


def update_department(
    session: Session, department_id: uuid.UUID, *, name: str | None = None,
    parent_id: uuid.UUID | None = None, parent_set: bool = False, enabled: bool | None = None,
) -> Department:
    department = load_department(session, department_id)
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise AppError("DEPARTMENT_NAME_REQUIRED", "部门名称不能为空", 422)
        if _name_taken(session, cleaned, exclude_id=department.id):
            raise AppError("DEPARTMENT_NAME_EXISTS", "部门名称已存在", 409)
        department.name = cleaned
    if parent_set:
        if parent_id is not None:
            load_department(session, parent_id)
            if _would_cycle(session, department.id, parent_id):
                raise AppError("DEPARTMENT_CYCLE", "不能把部门移动到自己或自己的子部门下", 409)
        department.parent_id = parent_id
    if enabled is not None:
        department.enabled = enabled
    session.commit()
    session.refresh(department)
    return department


def set_department_enabled(session: Session, department_id: uuid.UUID, enabled: bool) -> Department:
    department = load_department(session, department_id)
    department.enabled = enabled
    session.commit()
    session.refresh(department)
    return department


# ---------------------------------------------------------------- 角色

def _role_user_count(session: Session, role_id: uuid.UUID) -> int:
    return session.scalar(
        select(func.count()).select_from(user_roles).where(user_roles.c.role_id == role_id)
    ) or 0


def _role_document_count(session: Session, role_id: uuid.UUID) -> int:
    return session.scalar(
        select(func.count(func.distinct(DocumentAcl.document_id))).where(
            DocumentAcl.subject_type == SubjectType.ROLE, DocumentAcl.subject_id == role_id,
        )
    ) or 0


def role_payload(session: Session, role: Role) -> dict:
    codes = sorted(permission.code for permission in role.permissions)
    return {
        "id": role.id, "name": role.name, "description": role.description,
        "enabled": role.enabled, "created_at": role.created_at, "updated_at": role.updated_at,
        "user_count": _role_user_count(session, role.id),
        "document_count": _role_document_count(session, role.id),
        "permissions": codes, "permission_count": len(codes),
    }


def list_roles(session: Session, page: int = 1, page_size: int = 50) -> tuple[list[dict], int]:
    total = session.scalar(select(func.count()).select_from(Role)) or 0
    rows = list(session.scalars(
        select(Role).options(selectinload(Role.permissions))
        .order_by(Role.created_at.asc()).offset((page - 1) * page_size).limit(page_size)
    ))
    return [role_payload(session, role) for role in rows], total


def _validate_permission_codes(session: Session, codes: list[str]) -> list[str]:
    unique = list(dict.fromkeys(code.strip() for code in codes if code and code.strip()))
    unknown = [code for code in unique if code not in PERMISSION_CODES]
    if unknown:
        raise AppError("PERMISSION_CODE_INVALID", "存在无效的功能权限码", 422, {"codes": unknown})
    return unique


def set_role_permissions(session: Session, role: Role, codes: list[str]) -> dict:
    """覆盖设置角色权限，返回新增/移除的权限码；不修改用户角色绑定。"""
    desired = set(_validate_permission_codes(session, codes))
    current = {permission.code for permission in role.permissions}
    added = sorted(desired - current)
    removed = sorted(current - desired)
    if added or removed:
        session.execute(delete(role_permissions).where(role_permissions.c.role_id == role.id))
        if desired:
            session.execute(
                role_permissions.insert(),
                [{"role_id": role.id, "permission_code": code} for code in sorted(desired)],
            )
        # 触碰角色时间戳，让基于权限指纹的回答缓存立即失效。
        role.updated_at = datetime.now(UTC)
        session.commit()
        session.expire(role, ["permissions"])
    return {"added": added, "removed": removed}


def load_role(session: Session, role_id: uuid.UUID) -> Role:
    role = session.scalar(
        select(Role).where(Role.id == role_id).options(selectinload(Role.permissions))
    )
    if role is None:
        raise AppError("ROLE_NOT_FOUND", "角色不存在", 404)
    return role


def _role_name_taken(session: Session, name: str, exclude_id: uuid.UUID | None = None) -> bool:
    filters = [Role.name == name]
    if exclude_id is not None:
        filters.append(Role.id != exclude_id)
    return session.scalar(select(Role.id).where(*filters)) is not None


def create_role(
    session: Session, *, name: str, description: str | None, enabled: bool,
    permissions: list[str] | None = None,
) -> Role:
    cleaned = name.strip()
    if not cleaned:
        raise AppError("ROLE_NAME_REQUIRED", "角色名称不能为空", 422)
    if _role_name_taken(session, cleaned):
        raise AppError("ROLE_NAME_EXISTS", "角色名称已存在", 409)
    role = Role(name=cleaned, description=description, enabled=enabled)
    session.add(role)
    session.commit()
    session.refresh(role)
    if permissions:
        set_role_permissions(session, role, permissions)
    return role


def update_role(
    session: Session, role_id: uuid.UUID, *, name: str | None = None,
    description: str | None = None, description_set: bool = False, enabled: bool | None = None,
) -> Role:
    role = load_role(session, role_id)
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise AppError("ROLE_NAME_REQUIRED", "角色名称不能为空", 422)
        if _role_name_taken(session, cleaned, exclude_id=role.id):
            raise AppError("ROLE_NAME_EXISTS", "角色名称已存在", 409)
        role.name = cleaned
    if description_set:
        role.description = description
    if enabled is not None:
        role.enabled = enabled
    session.commit()
    session.refresh(role)
    return role


def set_role_enabled(session: Session, role_id: uuid.UUID, enabled: bool) -> Role:
    role = load_role(session, role_id)
    role.enabled = enabled
    session.commit()
    session.refresh(role)
    return role


def set_role_users(session: Session, role_id: uuid.UUID, user_ids: list[uuid.UUID]) -> Role:
    role = load_role(session, role_id)
    ids = list(dict.fromkeys(user_ids))
    if ids:
        users = list(session.scalars(select(User).where(User.id.in_(ids))).all())
        missing = [item for item in ids if item not in {user.id for user in users}]
        if missing:
            raise AppError("USER_NOT_FOUND", "指定的用户不存在", 404, {"ids": [str(item) for item in missing]})
    session.execute(delete(user_roles).where(user_roles.c.role_id == role_id))
    if ids:
        session.execute(user_roles.insert(), [{"user_id": user_id, "role_id": role_id} for user_id in ids])
    session.commit()
    session.refresh(role)
    return role
