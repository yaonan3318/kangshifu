# P1 升级说明（康师傅公司知识助手）

P1 在既有 P0（上传、解析、OCR、切片、混合检索、多知识库、回收站、检索实验室）之上补齐
“会话持久化、问答页面改版、性能优化、助手角色、本地账号与文档权限、答案反馈、运营统计、审计与外发控制”。
所有数据都在原 PostgreSQL 中增量新增，不会清空历史资料。

## 数据库迁移

新增迁移（按顺序执行，均从 0006 之后的编号开始）：

| 迁移 | 内容 |
| --- | --- |
| `0007_chat_sessions` | chat_sessions / chat_messages / chat_message_sources，历史引用快照 |
| `0008_answer_metrics` | chat_messages.metrics JSONB（阶段耗时、token 数） |
| `0009_assistants` | assistants / assistant_knowledge_bases，自动创建默认助手并绑定历史会话 |
| `0010_identity_permissions` | users / departments / roles / user_roles / document_acl / auth_sessions；documents.visibility、owner_user_id |
| `0011_audit_external_control` | audit_logs；documents.sensitivity_level、external_llm_allowed |
| `0012_answer_feedback` | answer_feedback |
| `0013_identity_management` | 用户/部门/角色的管理字段与唯一约束 |
| `0014_audit_completion` | 审计补全（成功/失败、request_id、error_code） |
| `0015_feedback_ranking` | 反馈排序统计表与索引 |
| `0016_feedback_documents` | answer_feedback_documents（多文档反馈归因） |
| `0017_assistant_runtime_policy` | 助手级 DeepSeek / Harness 运行策略 |
| `0018_function_rbac` | permissions / role_permissions，幂等写入权限码与四个默认角色 |

启动或升级：执行 `./scripts/setup.sh`（内部会 `alembic upgrade head`）后 `./scripts/start.sh`。

回滚：单批可用 `alembic downgrade -1`（逐级回滚，例如
`alembic downgrade 0017_assistant_runtime_policy`）。`0018_function_rbac` 的 downgrade
只删除 `permissions` / `role_permissions` 两张表，保留角色记录，避免破坏既有用户角色分配。

## 首次登录与管理员

- 首次启动自动创建管理员账号：`admin` / `admin123`（通过
  `COMPANY_SEARCH_ADMIN_PASSWORD` 可修改；上线前请务必修改）。
- 登录使用本地账号 + HttpOnly 会话 Cookie；密码以 bcrypt 存储。

## 主要新配置（backend/.env）

```env
# 快速问答模式（默认，回答后模型驻留 5 分钟）；改为 0 即节省内存模式（回答后立即释放）
COMPANY_SEARCH_OLLAMA_KEEP_ALIVE=5m
# 相同问题 + 资料版本 + 检索配置命中内存回答缓存
COMPANY_SEARCH_ANSWER_CACHE_ENABLED=true
# 首次启动引导管理员账号
COMPANY_SEARCH_ADMIN_PASSWORD=admin123
```

## 功能级 RBAC（0018）

两层权限同时生效，互不替代：

1. **功能权限**（本节的 `permissions` / `role_permissions`）：决定能否调用某类接口；
2. **文档 ACL**（`document_acl` + visibility）：决定能看到/管理哪些资料。

用户有效功能权限 = 所有**启用角色**权限的并集；停用用户无权限，停用角色立即失效；
`is_super_admin=true` 自动拥有全部权限（含 Harness）。HARNESS_USE 仅超级管理员有效，
普通角色即使绑定也不能绕过原管理员限制。

### 固定权限码

| 权限码 | 名称 | 分类 |
| --- | --- | --- |
| `ANSWER_USE` | 知识问答 | 基础使用 |
| `SEARCH_USE` | 资料检索 | 基础使用 |
| `DOCUMENT_VIEW` | 查看资料 | 基础使用 |
| `DOCUMENT_UPLOAD` | 上传资料 | 资料管理 |
| `DOCUMENT_MANAGE` | 管理资料 | 资料管理 |
| `KNOWLEDGE_BASE_MANAGE` | 管理知识库 | 资料管理 |
| `RETRIEVAL_LAB_USE` | 检索实验室 | 系统运营 |
| `ASSISTANT_MANAGE` | 助手管理 | 系统运营 |
| `IDENTITY_MANAGE` | 身份与角色管理 | 系统运营 |
| `AUDIT_VIEW` | 审计日志 | 系统运营 |
| `STATS_VIEW` | 运营统计 | 系统运营 |
| `HARNESS_USE` | Harness 运维（仅超级管理员） | Harness |

### 默认角色（迁移幂等创建，不修改现有用户）

| 角色 | 权限 |
| --- | --- |
| 普通员工 | `ANSWER_USE`、`SEARCH_USE`、`DOCUMENT_VIEW` |
| 资料维护员 | 普通员工 + `DOCUMENT_UPLOAD`、`DOCUMENT_MANAGE` |
| 知识库管理员 | 资料维护员 + `KNOWLEDGE_BASE_MANAGE` |
| 系统管理员 | 除 `HARNESS_USE` 外的全部后台管理权限 |

### 接口 ↔ 权限映射

| 接口 | 权限 |
| --- | --- |
| `POST /api/answer/stream`、`POST /api/answer/warmup` | `ANSWER_USE` |
| `POST /api/search` | `SEARCH_USE` |
| `GET /api/documents`、`/{id}`、`/{id}/content`、`/{id}/download`、`/{id}/versions` | `DOCUMENT_VIEW` + 文档 READ ACL |
| `POST /api/documents/upload`、`POST /api/batches*` | `DOCUMENT_UPLOAD` |
| `PATCH/DELETE /api/documents/{id}`、`enable`、`disable`、`restore`、`reprocess`、`purge`、`PUT access`、`PATCH external-policy`、`GET acl` | `DOCUMENT_MANAGE` + 文档 MANAGE ACL |
| `GET /api/knowledge-bases` | `ANSWER_USE` / `SEARCH_USE` / `DOCUMENT_VIEW` 任一 |
| `POST/PATCH /api/knowledge-bases*`、`enable`、`disable` | `KNOWLEDGE_BASE_MANAGE` |
| `/api/retrieval-lab/*` | `RETRIEVAL_LAB_USE` |
| `/api/assistants` 写操作与知识库绑定 | `ASSISTANT_MANAGE` |
| `/api/users/*`、`/api/departments/*`、`/api/roles/*` | `IDENTITY_MANAGE` |
| `GET /api/documents/acl-references` | `DOCUMENT_MANAGE`（仅 ACL 编辑引用数据） |
| `/api/audit/logs` | `AUDIT_VIEW` |
| `/api/stats/*` | `STATS_VIEW` |
| `/api/harness/*` | 超级管理员 + `HARNESS_USE` |

- `GET /api/auth/me` 返回当前用户 `permissions`，前端据此恢复菜单，不按角色名推算。
- 后端逐接口校验，前端隐藏按钮不是安全控制；无权限返回 403 `PERMISSION_DENIED`，
  未登录返回 401 `AUTH_REQUIRED`。
- 权限拒绝写入 `authorization_denied`（上传/知识库另有 `document_upload_denied` /
  `knowledge_base_manage_denied`），审计失败不影响原始 403 响应。
- 文档支持 `PRIVATE / COMPANY / DEPARTMENT / ROLE / USER`；旧资料默认 COMPANY，升级不影响检索。
- 敏感级别 `CONFIDENTIAL / RESTRICTED` 或 `external_llm_allowed=false` 的资料命中后，
  禁止发送 DeepSeek，页面提示“资料策略禁止使用外部模型”。
- 所有外发请求与关键操作写入 audit_logs（登录/上传/下载/删除/恢复/权限变更/DeepSeek 调用…）。

## Mac 功能权限验收手册

前置：使用专用测试库（不要用业务库）：

```bash
COMPANY_SEARCH_TEST_DATABASE_URL="postgresql+psycopg://company_search:company_search@127.0.0.1:54329/company_search_test" \
  backend/.venv/bin/python -m pytest backend/tests/test_p1_permission_integration.py -v
```

手工账号：`admin`（超管）、`employee`（普通员工）、`maintainer`（资料维护员）、
`kb_admin`（知识库管理员）、`no_role`（无角色）。验收矩阵：

| 操作 | employee | maintainer | kb_admin | no_role | admin |
| --- | --- | --- | --- | --- | --- |
| 问答 | ✅ | ✅ | ✅ | ❌ | ✅ |
| 检索 | ✅ | ✅ | ✅ | ❌ | ✅ |
| 查看有权资料 | ✅ | ✅ | ✅ | ❌ | ✅ |
| 上传 | ❌ | ✅ | ✅ | ❌ | ✅ |
| 管理本人有 MANAGE 的资料 | ❌ | ✅ | ✅ | ❌ | ✅ |
| 管理知识库 | ❌ | ❌ | ✅ | ❌ | ✅ |
| 系统管理 | ❌ | ❌ | 按配置 | ❌ | ✅ |
| Harness | ❌ | ❌ | ❌ | ❌ | ✅ |

额外验证：停用角色后刷新页面，菜单与接口权限均失效；保持旧页面撤销权限后下一次请求返回 403；
修改角色权限无需重建账号；用户 A 的缓存答案不会被无权用户 B 获取；COMPANY 资料仍需
`DOCUMENT_VIEW`；ROLE/DEPARTMENT/USER/PRIVATE 继续遵守文档 ACL；DeepSeek 不接收无权或禁止外发的资料。

## 验收建议

1. 登录 admin 后进入“知识问答”，提问，切到“资料库”再返回——问题和答案仍在。
2. 正在生成时切页再返回，生成继续；刷新后左侧会话可恢复历史。
3. 连续提问第二次明显更快；回答卡片显示首字与总耗时；停用资料后相同问题不再命中缓存。
4. “助手管理”可新建/编辑助手、绑定知识库与系统提示词，聊天顶部可切换助手。
5. “资料库-详情”可看到 visibility；上传人/管理员可在文档上设置可见范围。
6. 对回答点赞/点踩后，管理员在“反馈管理”可查看并标记处理。
7. “运营统计”展示近期问答量、首字/回答/检索耗时、成功率、无答案与热点资料。
8. 回答使用 DeepSeek 时“审计日志”记录 external_llm_call。

## 说明

- 所有批次已分别提交：P1-1/2（会话+页面）、P1-3（性能）、P1-4（助手）、P1-5（账号权限）、
  P1-8（审计/外发控制）、P1-6（反馈）、P1-7（统计）。
