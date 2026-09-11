# 助手可见性与知识权限实施计划

> 交付给 DeepSeek：按本计划实现，不执行 `git commit` 和 `git push`。

## 目标

实现“综合助手 + 专业助手”的混合模式，并把知识权限作为唯一事实来源：

- 综合助手始终对具备 `ANSWER_USE` 的登录用户可见，但只能检索该用户有权访问的资料。
- 专业助手绑定一个或多个知识库；用户对绑定范围内至少存在一项有效读取权限时，该助手才可见。
- 专业助手实际检索范围是“助手绑定知识库”与“用户可读资料”的交集。
- 跨部门长期访问通过角色授权，少量例外通过用户授权，敏感资料支持临时授权。
- 显式拒绝优先于部门、角色、用户及公司级允许。
- 运维、工资处理等操作型助手除资料权限外，还必须具备对应功能权限。
- 前端隐藏只是体验，所有接口必须由后端重新鉴权。

## 不采用的设计

- 不为普通问答助手再建立部门/角色/用户三套独立授权关系，避免助手权限与资料权限不一致。
- 不允许 `allow_all_knowledge_bases=true` 绕过文档 ACL。
- 不把“能看到助手”等同于“能看到助手绑定的全部资料”。
- 不在前端传入可访问知识库 ID 后直接信任该参数。

## 任务 1：补充权限数据模型

修改：

- `backend/app/models/identity.py`
- `backend/app/models/knowledge_base.py`
- `backend/app/models/assistant.py`
- `backend/app/models/__init__.py`
- 新增一份 Alembic migration

### 1.1 知识库 ACL

新增 `KnowledgeBaseAcl`：

- `id: UUID`
- `knowledge_base_id: UUID`
- `subject_type: DEPARTMENT | ROLE | USER`
- `subject_id: UUID`
- `permission: READ | MANAGE`
- `effect: ALLOW | DENY`
- `expires_at: timestamptz | null`
- `reason: text | null`
- `created_by: UUID | null`
- `created_at / updated_at`

索引至少覆盖：

- `(knowledge_base_id, subject_type, subject_id)`
- `(subject_type, subject_id, effect, expires_at)`

同一知识库、主体、权限只保留一条有效规则；更新授权采用 upsert，不制造重复记录。

### 1.2 扩展文档 ACL

在现有 `DocumentAcl` 增加：

- `effect: ALLOW | DENY`，旧数据迁移为 `ALLOW`
- `expires_at: timestamptz | null`
- `reason: text | null`
- `created_by: UUID | null`

### 1.3 助手类型

在 `Assistant` 增加：

- `assistant_type: GENERAL | KNOWLEDGE | OPERATION`
- `required_permission_code: varchar | null`

迁移规则：

- `DEFAULT_ASSISTANT_ID` 对应助手设为 `GENERAL`，并保留 `allow_all_knowledge_bases=true`。
- 其他现有助手默认设为 `KNOWLEDGE`。
- 不要仅凭名称猜测助手类型；运维等助手由管理员显式改成 `OPERATION` 并配置功能权限。

## 任务 2：统一资料权限解析器

修改 `backend/app/services/permissions.py`，不要在各 API 中复制 SQL 条件。

新增或重构以下能力：

```python
class PermissionResolver:
    def readable_document_clause(self): ...
    def manageable_document_clause(self): ...
    def readable_knowledge_base_ids(self) -> set[UUID]: ...
    def can_read_knowledge_base(self, knowledge_base_id: UUID) -> bool: ...
    def require_document_read(self, document: Document): ...
    def require_knowledge_base_read(self, knowledge_base_id: UUID): ...
```

统一规则：

1. 超级管理员按现有系统语义处理，但仍记录访问审计。
2. 只计算未过期规则：`expires_at IS NULL OR expires_at > now()`。
3. 任意匹配的有效 `DENY` 优先于所有 `ALLOW`。
4. 知识库 `DENY` 会拒绝该知识库内全部文档。
5. 文档 `DENY` 只拒绝该文档。
6. 文档允许来源可以是文档可见性、知识库 ALLOW 或文档 ALLOW。
7. `COMPANY` 文档也必须受显式 DENY 约束，不能因为是公司资料直接绕过拒绝。
8. 已停用、软删除、未完成索引的文档不可读、不可检索。
9. 已停用知识库不可读、不可用于助手可见性判断。

`readable_knowledge_base_ids()` 的定义应是用户至少能读取该知识库本身，或至少能读取其中一篇有效文档；不要因为能看知识库名称就默认能看全部文档。

## 任务 3：新增助手访问解析器

新增：`backend/app/services/assistant_access.py`

建议接口：

```python
class AssistantAccessResolver:
    def list_available(self) -> list[Assistant]: ...
    def can_use(self, assistant: Assistant) -> bool: ...
    def require_use(self, assistant_id: UUID) -> Assistant: ...
    def effective_knowledge_base_ids(self, assistant: Assistant) -> set[UUID]: ...
```

判断规则：

- 所有助手必须 `enabled=true`，用户必须有 `ANSWER_USE`。
- `GENERAL`：始终可用；有效知识库范围等于用户当前可读范围。
- `KNOWLEDGE`：助手绑定知识库与用户可读知识库交集非空时可用；有效范围就是该交集。
- `OPERATION`：先满足专业助手规则，再检查 `required_permission_code`；未配置功能权限码时默认拒绝，不可宽松放行。
- 找不到助手、助手停用、用户无权使用时，对普通用户返回统一的 404 或通用 403，避免泄露隐藏助手信息。

不要按助手名称、部门名称写 if/else。

## 任务 4：收口助手 API

修改：

- `backend/app/api/assistants.py`
- `backend/app/schemas/assistant.py`
- 必要时新增 `backend/app/schemas/access.py`

接口行为：

- `GET /api/assistants/available`：登录用户获取自己可用的启用助手。
- `GET /api/assistants`：改为管理员管理列表，要求 `ASSISTANT_MANAGE`；如为兼容旧前端，也可以保留参数，但必须明确区分管理列表和可用列表。
- `GET /api/assistants/{id}/welcome`：调用 `require_use()`，知识库名称只返回用户可读且处于有效交集的项。
- 创建、修改助手支持 `assistant_type`、`required_permission_code`，并校验权限码真实存在。
- 绑定知识库仍由 `ASSISTANT_MANAGE` 控制。
- 管理员可以把综合助手绑定为空，但综合助手实际范围仍由用户权限计算；建议 UI 对综合助手隐藏具体知识库勾选，显示“跟随用户有效权限”。

## 任务 5：收口所有生产调用链

必须逐一检查并修改：

- `backend/app/api/answer.py`
- `backend/app/api/chat.py`
- `backend/app/services/chat.py`
- `backend/app/services/rag.py`
- `backend/app/services/rag_flow.py`
- `backend/app/services/search.py`
- Harness 相关 API 和服务
- 重新生成、恢复生成、后台任务执行链

要求：

1. 创建会话时校验助手可用性。
2. 切换助手时重新校验，不允许伪造 `assistant_id`。
3. 每次问答执行前再次校验，防止会话创建后权限被撤销。
4. `RagService._assistant_config()` 不再自行宽松加载助手，改用解析器返回的助手和有效知识库范围。
5. `GENERAL` 的“全部知识库”含义是用户可访问的全部，不是数据库中的全部。
6. 专业助手检索条件必须是 `assistant KB ∩ user KB/document ACL`。
7. 请求中的 `knowledge_base_id` 必须处于有效范围，否则拒绝。
8. 搜索、引用详情、下载、预览、导出都再次走文档权限解析器。
9. OPERATION/Harness 除助手使用权限外，保持现有每次人工确认、dry-run 和差异预览规则。
10. 权限变化后，正在执行但尚未取证的任务应拒绝继续；已生成历史消息仍按会话所有权展示，但引用原文再次打开时重新鉴权。

## 任务 6：缓存隔离和失效

当前回答缓存已有用户权限范围字段，但必须增强：

- 缓存键包含 `user_id`、`assistant_id`、有效知识库 ID 集合及 ACL 版本指纹。
- 知识库 ACL、文档 ACL、用户角色、所属部门、角色停用、助手绑定、助手停用发生变化后，不得命中旧授权缓存。
- 简单方案：这些变更时清空进程内回答缓存。
- 推荐方案：维护权限版本号并进入缓存键。
- 禁止不同用户共享包含内部资料的回答缓存，除非证明有效权限集合完全一致且不会泄露身份信息；本阶段优先按用户隔离。

## 任务 7：授权管理 API

新增管理员接口，全部要求对应管理权限并写审计：

```text
GET    /api/knowledge-bases/{id}/acl
PUT    /api/knowledge-bases/{id}/acl/{subject_type}/{subject_id}
DELETE /api/knowledge-bases/{id}/acl/{subject_type}/{subject_id}

GET    /api/documents/{id}/acl
PUT    /api/documents/{id}/acl/{subject_type}/{subject_id}
DELETE /api/documents/{id}/acl/{subject_type}/{subject_id}
```

PUT 请求支持：`permission`、`effect`、`expires_at`、`reason`。

校验：

- `expires_at` 必须晚于当前时间。
- subject 必须存在且启用。
- 知识库管理用 `KNOWLEDGE_BASE_MANAGE`；文档授权用 `DOCUMENT_MANAGE`。
- 返回有效状态、是否已过期及授权来源，便于前端展示。

## 任务 8：前端行为

修改助手选择及管理页面：

- 普通用户只请求 `/api/assistants/available`。
- 用户只能看到自己可用的助手；综合助手排在第一位，专业助手按管理员排序或名称展示。
- 若上次选择的助手已无权限，自动回退综合助手，并提示“该助手权限已变更，已切换到综合助手”。
- 不向普通用户展示不可访问助手、不可访问知识库名称或“缺少某角色”等内部授权细节。
- 管理员助手表单增加助手类型和操作权限码。
- 综合助手显示“资料范围：跟随当前用户权限”。
- 专业助手显示绑定知识库，但只有管理员可编辑。

新增知识库权限抽屉：

- 部门、角色、用户三种主体。
- 允许/拒绝。
- 永久/指定到期时间。
- 授权原因。
- 当前有效、即将到期、已过期状态。
- 明确提示“拒绝优先于允许”。

文档详情沿用相同 ACL 编辑组件，避免两套 UI 规则不一致。

## 任务 9：审计

使用现有 `AuditLog`，至少记录：

- `knowledge_base_acl_granted/updated/revoked/expired`
- `document_acl_granted/updated/revoked/expired`
- `assistant_access_allowed/denied`
- `assistant_scope_changed`
- `assistant_operation_requested/confirmed/denied`

审计 detail 包含主体类型、主体 ID、effect、到期时间、原因、助手 ID、知识库 ID；不得记录密码、API Key、完整工资内容等敏感正文。

高频问答不建议每个内部 SQL 判断都记日志，只记录一次最终访问决策和关键操作，避免审计表爆炸。

## 任务 10：测试

至少新增以下测试：

1. 普通研发用户可见综合、技术、项目助手，不可见人事助手。
2. 综合助手只检索该用户可读资料，不因 `allow_all_knowledge_bases` 越权。
3. 专业助手只检索“绑定范围与用户权限”的交集。
4. 给研发角色增加人事知识库长期 ALLOW 后，人事助手自动出现。
5. 给单个用户增加临时 ALLOW 后助手出现，到期后自动消失。
6. 任意有效 DENY 覆盖公司可见、部门、角色和用户 ALLOW。
7. 文档级 DENY 不误伤同知识库其他文档。
8. 伪造不可见 assistant_id 调问答、welcome、会话创建、重新生成均被拒绝。
9. OPERATION 助手无功能权限被拒绝；有权限仍必须完成人工确认。
10. 助手停用、知识库停用、角色停用后立即失效。
11. 两个权限不同用户不会命中彼此的回答缓存。
12. 普通用户接口不会泄露隐藏助手和知识库名称。
13. 管理员 ACL 增删改及失败操作均进入审计。
14. 原有文档 READ/MANAGE、软删除、搜索、回答和 Harness 测试不回归。

## 验证命令

DeepSeek 必须真实执行并粘贴输出；没有运行的项目不得声称通过：

```bash
python -m compileall -q backend/app backend/migrations/versions backend/tests
git diff --check
npm --prefix frontend run build
```

环境具备依赖时继续：

```bash
cd backend
.venv/bin/python -m pytest -q
.venv/bin/alembic upgrade head
.venv/bin/alembic current
```

建议额外执行：

```bash
git status --short
```

## DeepSeek 最终报告

```markdown
1. 数据库模型和迁移改了什么。
2. 权限计算的明确优先级。
3. 哪些 API 已完成后端鉴权收口。
4. 综合助手、专业助手、操作助手的实际行为。
5. 前端新增或调整了什么。
6. 新增测试列表。
7. 每条验证命令的真实输出。
8. 因环境原因未运行的检查。
9. 尚存风险和兼容性问题。
10. git status --short 输出。
11. 不执行 git commit 和 git push。
```

## 推荐分批顺序

1. 数据库迁移、权限解析器及单元测试。
2. 助手访问解析器、可用助手 API 及测试。
3. Answer/Search/Chat/RAG/Harness 全链路收口。
4. 缓存隔离、审计和临时授权。
5. 管理端 ACL UI 与普通用户助手选择 UI。
6. 全量迁移、构建、测试和最终报告。

