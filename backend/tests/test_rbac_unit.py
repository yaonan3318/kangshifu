"""功能级 RBAC 纯单元测试：不依赖数据库，直接验证权限解析规则。

覆盖需求：超管全量、多角色并集、停用角色失效、无角色无权限、
默认角色边界、HARNESS_USE 仅超管、401/403 语义。
"""

from types import SimpleNamespace

import pytest

from app.errors import AppError
from app.services import rbac


def _permission(code: str) -> SimpleNamespace:
    return SimpleNamespace(code=code)


def _role(*codes: str, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(enabled=enabled, permissions=[_permission(code) for code in codes])


def _user(*roles, enabled: bool = True, super_admin: bool = False) -> SimpleNamespace:
    return SimpleNamespace(enabled=enabled, is_super_admin=super_admin, roles=list(roles))


def test_super_admin_has_all_permissions():
    user = _user(super_admin=True)
    assert rbac.effective_permissions(user) == rbac.PERMISSION_CODES
    for code in rbac.PERMISSION_CODES:
        assert rbac.has_permission(user, code) is True


def test_multiple_roles_union_permissions():
    user = _user(_role("ANSWER_USE"), _role("DOCUMENT_UPLOAD", "DOCUMENT_MANAGE"))
    assert rbac.effective_permissions(user) == {"ANSWER_USE", "DOCUMENT_UPLOAD", "DOCUMENT_MANAGE"}


def test_disabled_role_permissions_disappear_immediately():
    role = _role("DOCUMENT_UPLOAD")
    user = _user(role)
    assert rbac.has_permission(user, "DOCUMENT_UPLOAD") is True
    role.enabled = False
    assert rbac.has_permission(user, "DOCUMENT_UPLOAD") is False


def test_user_without_roles_has_no_permissions():
    user = _user()
    assert rbac.effective_permissions(user) == set()
    assert rbac.has_permission(user, "ANSWER_USE") is False


def test_disabled_user_has_no_permissions():
    user = _user(_role("ANSWER_USE"), enabled=False)
    assert rbac.effective_permissions(user) == set()
    assert rbac.has_permission(user, "ANSWER_USE") is False


def test_default_role_boundaries():
    employee = _user(_role(*rbac.DEFAULT_ROLES[0]["permissions"]))
    maintainer = _user(_role(*rbac.DEFAULT_ROLES[1]["permissions"]))
    kb_admin = _user(_role(*rbac.DEFAULT_ROLES[2]["permissions"]))

    assert rbac.has_permission(employee, "DOCUMENT_VIEW") is True
    assert rbac.has_permission(employee, "DOCUMENT_UPLOAD") is False
    assert rbac.has_permission(maintainer, "DOCUMENT_UPLOAD") is True
    assert rbac.has_permission(maintainer, "KNOWLEDGE_BASE_MANAGE") is False
    assert rbac.has_permission(kb_admin, "KNOWLEDGE_BASE_MANAGE") is True


def test_harness_use_requires_super_admin_even_if_role_grants_it():
    user = _user(_role("HARNESS_USE"))
    assert rbac.has_permission(user, "HARNESS_USE") is False
    assert "HARNESS_USE" not in rbac.effective_permissions(user)
    assert rbac.has_permission(_user(super_admin=True), "HARNESS_USE") is True


def test_require_permission_rejects_unauthenticated_with_401():
    with pytest.raises(AppError) as excinfo:
        rbac.require_permission(None, "ANSWER_USE")
    assert excinfo.value.status_code == 401
    assert excinfo.value.code == "AUTH_REQUIRED"


def test_require_permission_rejects_without_permission_with_403():
    user = _user(_role("DOCUMENT_VIEW"))
    with pytest.raises(AppError) as excinfo:
        rbac.require_permission(user, "DOCUMENT_UPLOAD")
    assert excinfo.value.status_code == 403
    assert excinfo.value.code == "PERMISSION_DENIED"
    assert excinfo.value.details == {"permission": "DOCUMENT_UPLOAD"}


def test_require_permission_passes_with_permission():
    user = _user(_role("DOCUMENT_UPLOAD"))
    assert rbac.require_permission(user, "DOCUMENT_UPLOAD") is user


def test_require_any_permission_supports_multiple_codes():
    user = _user(_role("SEARCH_USE"))
    assert rbac.require_any_permission(user, ("ANSWER_USE", "SEARCH_USE")) is user
    with pytest.raises(AppError) as excinfo:
        rbac.require_any_permission(user, ("ANSWER_USE", "DOCUMENT_VIEW"))
    assert excinfo.value.status_code == 403
