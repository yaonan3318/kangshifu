"""功能级 RBAC：固定权限码目录、默认角色定义与权限解析。

规则：
- 用户有效权限 = 所有**启用**角色权限的并集；
- 停用用户没有任何权限；停用角色不参与合并；
- 超级管理员自动拥有全部权限；
- HARNESS_USE 只对超级管理员生效，普通角色即使绑定也不能绕过原管理员限制。
"""

from app.errors import AppError
from app.models import User
from app.services.permissions import require_user

# ---------------------------------------------------------------- 固定权限码

HARNESS_USE = "HARNESS_USE"

# 权限码目录：迁移会按此幂等写入 permissions 表；顺序即前端展示顺序。
PERMISSIONS: list[dict] = [
    {"code": "ANSWER_USE", "name": "知识问答", "category": "basic", "sort_order": 10,
     "description": "使用知识问答与助手进行提问"},
    {"code": "SEARCH_USE", "name": "资料检索", "category": "basic", "sort_order": 20,
     "description": "使用关键词与语义混合检索"},
    {"code": "DOCUMENT_VIEW", "name": "查看资料", "category": "basic", "sort_order": 30,
     "description": "查看自己有权访问的资料"},
    {"code": "DOCUMENT_UPLOAD", "name": "上传资料", "category": "document", "sort_order": 40,
     "description": "上传单文件与批量导入资料"},
    {"code": "DOCUMENT_MANAGE", "name": "管理资料", "category": "document", "sort_order": 50,
     "description": "编辑、启停、删除、恢复及设置文档权限"},
    {"code": "KNOWLEDGE_BASE_MANAGE", "name": "管理知识库", "category": "document", "sort_order": 60,
     "description": "创建、编辑与启停知识库"},
    {"code": "RETRIEVAL_LAB_USE", "name": "检索实验室", "category": "operations", "sort_order": 70,
     "description": "使用检索诊断与评测工具"},
    {"code": "ASSISTANT_MANAGE", "name": "助手管理", "category": "operations", "sort_order": 80,
     "description": "创建、编辑、启停助手并绑定知识库"},
    {"code": "IDENTITY_MANAGE", "name": "身份与角色管理", "category": "operations", "sort_order": 90,
     "description": "管理用户、部门、角色与角色权限"},
    {"code": "AUDIT_VIEW", "name": "审计日志", "category": "operations", "sort_order": 100,
     "description": "查看审计日志"},
    {"code": "STATS_VIEW", "name": "运营统计", "category": "operations", "sort_order": 110,
     "description": "查看运营统计与问答追踪"},
    {"code": "FEEDBACK_VIEW", "name": "反馈查看", "category": "operations", "sort_order": 130,
     "description": "查看反馈处理队列与详情"},
    {"code": "FEEDBACK_MANAGE", "name": "反馈处理", "category": "operations", "sort_order": 140,
     "description": "处理反馈、变更状态与记录结论"},
    {"code": "FEEDBACK_ASSIGN", "name": "反馈分配", "category": "operations", "sort_order": 150,
     "description": "分配反馈负责人与优先级"},
    {"code": "FEEDBACK_VERIFY", "name": "反馈复验", "category": "operations", "sort_order": 160,
     "description": "重新运行原问题并判定是否解决"},
    {"code": "FEEDBACK_STATISTICS", "name": "反馈统计", "category": "operations", "sort_order": 170,
     "description": "查看反馈运营统计与配置对比"},
    {"code": HARNESS_USE, "name": "Harness 运维", "category": "harness", "sort_order": 120,
     "description": "执行 Kubernetes 运维工具（仅超级管理员）"},
]

PERMISSION_CODES: set[str] = {item["code"] for item in PERMISSIONS}
PERMISSION_NAMES: dict[str, str] = {item["code"]: item["name"] for item in PERMISSIONS}
PERMISSION_CATEGORIES: list[dict] = [
    {"key": "basic", "label": "基础使用"},
    {"key": "document", "label": "资料管理"},
    {"key": "operations", "label": "系统运营"},
    {"key": "harness", "label": "Harness（仅超级管理员）"},
]

# 默认角色：迁移幂等创建，不自动修改现有用户角色。
_BASE = ["ANSWER_USE", "SEARCH_USE", "DOCUMENT_VIEW"]
_MAINTAINER = [*_BASE, "DOCUMENT_UPLOAD", "DOCUMENT_MANAGE"]
_KB_ADMIN = [*_MAINTAINER, "KNOWLEDGE_BASE_MANAGE"]
_SYSTEM_ADMIN = [code for code in PERMISSION_CODES if code != HARNESS_USE]

DEFAULT_ROLES: list[dict] = [
    {"name": "普通员工", "description": "日常问答与查看有权资料", "permissions": _BASE},
    {"name": "资料维护员", "description": "在普通员工基础上上传与管理资料", "permissions": _MAINTAINER},
    {"name": "知识库管理员", "description": "在资料维护员基础上管理知识库", "permissions": _KB_ADMIN},
    {"name": "系统管理员", "description": "除 Harness 外的全部后台管理权限", "permissions": _SYSTEM_ADMIN},
]


def permission_catalog() -> list[dict]:
    """返回权限码目录（含分类），供角色编辑页面渲染。"""
    return [
        {
            "code": item["code"], "name": item["name"], "description": item["description"],
            "category": item["category"], "sort_order": item["sort_order"],
        }
        for item in PERMISSIONS
    ]


# ---------------------------------------------------------------- 解析

def effective_permissions(user: User | None) -> set[str]:
    """返回用户有效权限码集合；停用用户为空，超级管理员为全部。"""
    if user is None or not user.enabled:
        return set()
    if user.is_super_admin:
        return set(PERMISSION_CODES)
    codes: set[str] = set()
    for role in user.roles:
        if not role.enabled:
            continue
        for permission in role.permissions:
            codes.add(permission.code)
    codes.discard(HARNESS_USE)
    return codes


def has_permission(user: User | None, permission_code: str) -> bool:
    """判断用户是否拥有某权限；未登录/停用/Harness 非超管一律为否。"""
    if user is None or not user.enabled:
        return False
    if user.is_super_admin:
        return True
    if permission_code == HARNESS_USE:
        return False
    return permission_code in effective_permissions(user)


def has_any_permission(user: User | None, permission_codes: list[str] | tuple[str, ...]) -> bool:
    return any(has_permission(user, code) for code in permission_codes)


def require_permission(user: User | None, permission_code: str) -> User:
    """校验功能权限：未登录 401，无权限 403 PERMISSION_DENIED（带权限码）。"""
    current = require_user(user)
    if has_permission(current, permission_code):
        return current
    raise AppError(
        "PERMISSION_DENIED", "当前账号没有此功能权限", 403,
        {"permission": permission_code},
    )


def require_any_permission(user: User | None, permission_codes: list[str] | tuple[str, ...]) -> User:
    current = require_user(user)
    if has_any_permission(current, permission_codes):
        return current
    raise AppError(
        "PERMISSION_DENIED", "当前账号没有此功能权限", 403,
        {"permission": list(permission_codes)},
    )
