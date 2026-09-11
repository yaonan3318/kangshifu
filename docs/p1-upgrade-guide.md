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
| `0019_evaluation_sets` | evaluation_sets / retrieval_config_versions，扩展标准问题与运行记录 |
| `0020_search_accuracy` | documents 有效期字段 + retrieval_dictionary_entries 检索词典 |
| `0021_assistant_roles` | assistants 角色字段（答案模板/联网/无答案策略/能力）与六个预置助手 |
| `0022_chatflow` | chatflows / chatflow_versions 固定画布流程，assistants.chatflow_id 绑定 |
| `0023_knowledge_gaps` | knowledge_gaps 知识缺口中心 |
| `0024_document_understanding` | 知识库切片配置、文档作者/部门/主题/关联文档、父子切片字段 |
| `0025_expected_chunks` | 标准问题 `expected_chunk_ids`，用于真实片段召回率 |
| `0026_retrieval_log_ranks` | `chat_message_sources` 召回/精排前后排名，完善生产检索日志 |
| `0027_reliability_and_scope` | 引用快照 `document_version`（版本已更新提示）+ 助手 `allow_all_knowledge_bases`（知识库范围语义） |
| `0028_answer_jobs` | `answer_jobs` 生成任务表 + `documents.superseded_by_id`（替代版本）+ `document_chunks.parent_chunk_id`（父子切片） |

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

## P2-0 质量基线（评测集 + 检索配置版本）

P2-0 先建立后面所有优化的衡量标准，入口在“检索实验室”（需 `RETRIEVAL_LAB_USE`）。

### 评测集管理

- 创建/删除评测集，每个评测集绑定默认知识库。
- 添加标准问题：问题、正确文档、必须引用文档、禁止召回文档、答案关键点、是否应无答案。
- 支持 CSV / Excel(.xlsx) 批量导入，表头支持中英文别名；文档可用 UUID 或文件名。
- 支持批量运行评测。

### 评测指标

| 指标 | 含义 |
| --- | --- |
| 正确文档召回率 | 预期文档被召回的比例 |
| 正确片段召回率 | Top-K 内命中预期文档的片段相对预期文档的比例 |
| Top1/Top3/Top5 命中率 | 预期文档是否出现在前 K 个结果 |
| 答案关键点覆盖率 | 关键点出现在答案（或检索证据）中的比例 |
| 引用正确率 | 必须引用文档出现在引用中的比例 |
| 无答案判断正确率 | 无答案判断与预期一致的比例 |
| 首字耗时 / 完整回答耗时 | 检索耗时；勾选“同时生成答案”后为真实 LLM 首字与总耗时 |
| 禁止召回违规数 | 命中“不应召回文档”的用例数（应为 0） |

运行默认使用“检索证据”作为答案基线（确定性、无需大模型）；勾选“同时生成答案”后调用本地
千问生成真实答案并统计首字/总耗时与真实引用。

### 检索配置版本化

每次调整检索参数都可保存为配置版本，包含：关键词召回数量、向量召回数量、RRF 常数与权重、
Reranker 开关与模型、精排候选数量、相似度阈值、最低证据分数、单文档片段上限、最终片段数量、
Query Rewrite 同义词。运行评测时绑定某个配置版本，运行记录保存配置快照。

“对比两次运行”给出指标变化（右 - 左）、配置字段差异与逐用例变化，因此新旧版本可以在同一评测集
上量化对比，而不是只凭人工感觉判断。

### Mac 验收

```bash
COMPANY_SEARCH_TEST_DATABASE_URL="postgresql+psycopg://company_search:company_search@127.0.0.1:54329/company_search_test" \
  backend/.venv/bin/python -m pytest backend/tests/test_p1_permission_integration.py -k p2 -v
```

手工步骤：新建评测集 → 添加或导入标准问题 → 新建两个配置版本（如 v1 关键词 10 / v2 关键词 30）
→ 分别运行评测 → 对比两次运行，确认指标变化与配置差异符合预期。

## P2-1 检索准确性增强

在“检索实验室”的检索配置版本中开启，默认关闭以免改变既有行为与延迟。

### Query Rewrite 与多轮上下文补全

- 保留原始问题；只把改写结果用于检索，并在回答底部展示“实际检索问题”。
- 只读取最近若干轮（默认 3 轮）上下文；新建会话不继承；由模型判断是否依赖上下文，
  明显切换话题时保持原问题。
- 改写提示词明确要求“不得改变用户原意、不得添加用户没问的内容”。
- 模型失败时自动回退原问题，不阻塞检索。
- 检索实验室“本次检索过程”展示原始问题、补全后问题、实际检索问题与是否使用上下文。

### Multi-query 多查询召回

- 默认生成 2～4 个检索表达；分别执行关键词与向量召回，按 `chunk_id` 去重后做 RRF 融合，
  再交给 Reranker。
- 原始问题始终作为其中一个查询，避免只依赖模型生成的表达。

### Reranker 精排

- 在检索配置版本中配置开关、模型、精排候选数量与最终片段数量。
- 记录重排前后名次，检索实验室结果表展示“重排前/重排后”。
- 模型不可用时自动退化为 RRF 并给出提示；评测可对比启用前后的准确率与耗时。

### 元数据与结构化过滤

检索条件新增：知识库、文件类型、文档标签、部门、上传人、创建时间、文档有效期、
文档状态、文件夹路径、文档版本。**权限过滤始终先执行**，再叠加这些结构化条件。

### 中文检索优化

- 词典由管理员在“检索实验室 → 中文检索词典”维护，不写死在代码里；
  类别包括同义词、公司缩写/简称、专有名词，加载时构建双向映射（简称↔全称）。
- 支持中英文混合、拼写纠正（受限编辑距离，仅 ASCII 词）与词典扩展。
- 迁移会写入需求示例词条（K8s→Kubernetes、日报、气泡），管理员可增删改。

### Mac 验收

```bash
COMPANY_SEARCH_TEST_DATABASE_URL="postgresql+psycopg://company_search:company_search@127.0.0.1:54329/company_search_test" \
  backend/.venv/bin/python -m pytest backend/tests/test_p2_search_accuracy.py backend/tests/test_p1_permission_integration.py -k "p2" -v
```

手工步骤：新建配置版本并开启 Query Rewrite / Multi-query / Reranker 并设为默认 →
在检索实验室输入“日报中气泡后来怎么样了？”查看改写与多查询 → 在词典中新增“工单 → ticket”
后用“工单处理流程”检索，确认扩展词出现。

## P2-2 回答可靠性增强

### 答案置信度

综合召回分数、Reranker 分数、有效片段数量、多片段内容一致性与答案引用覆盖度计算，
页面只展示三级中文标签：**高可信 / 中等可信 / 资料不足**，不展示裸分数（原始分数保留在
`chat_messages.metrics.confidence` 供管理员调试）。

### 无答案与低置信度处理

- 资料不足时禁止模型猜测，返回固定提示“当前可访问的公司资料中没有找到足够依据。”。
- 区分四种情况：公司没有相关资料、有资料但无权访问、检索到低相关资料、本地模型不可用。
  “有资料但无权访问”只用于选择提示语，**不返回无权文档的名称**。
- 面板提供：推荐相关资料（仅限有权访问）、换一种问法、是否使用 DeepSeek 通用知识、
  提交“缺失知识”反馈。

### 引用真实性校验

生成完成后检查：引用编号是否存在、答案句子是否被引用片段支持、引用文档是否仍可访问。
无效引用与缺少依据的句子会被标记为“（推断）”，并在回答下方给出提示。

### 可追溯答案

点击引用后展示：文档名称、页码/幻灯片/工作表、命中原文、命中关键词、当前文档版本；
可跳转到资料库详情；有权限时可下载原文件。

### 答案结构模板

按问题类型（制度 / 技术 / 项目进度 / 对比 / 汇总 / 通用）注入不同的答案结构提示词，
例如制度问题按“结论、适用范围、办理步骤、注意事项”组织。

### Mac 验收

```bash
COMPANY_SEARCH_TEST_DATABASE_URL="postgresql+psycopg://company_search:company_search@127.0.0.1:54329/company_search_test" \
  backend/.venv/bin/python -m pytest backend/tests/test_p2_answer_quality.py backend/tests/test_p1_permission_integration.py -k "p2" -v
```

手工步骤：提问一个资料库没有的问题，确认返回固定提示与“缺失知识”反馈入口；提问一个有权资料
可回答的问题，确认出现“高可信/中等可信”标签与引用校验提示；点击引用查看版本、命中关键词与下载入口。

## P2-3 助手角色增强

### 助手配置字段

每个助手可配置：名称与头像、角色说明、系统提示词、可访问知识库、**默认答案模板**、
召回数量、温度、本地模型、是否允许 DeepSeek、是否允许 Harness、**是否允许联网**、
**无答案策略**，以及欢迎页的“能做什么/不能做什么”。

- 默认答案模板：`AUTO`（按问题类型自动）或固定为制度/技术/项目进度/对比/汇总/通用。
- 无答案策略：`SUGGEST`（提示并推荐资料）、`STRICT`（只给固定提示，不用通用知识补答）、
  `GENERAL`（允许通用知识补充）。
- 联网开关当前仅记录策略，不发起联网请求（为后续能力预留）。

### 预置助手

迁移 `0021_assistant_roles` 幂等预置六个角色助手：康师傅综合助手、人事制度助手、技术研发助手、
产品资料助手、运维助手、项目进度助手；默认助手升级为“康师傅综合助手”，保留原 ID 与会话绑定。

### 用户端隐藏技术选项

普通用户页面只展示可理解的信息：当前助手、使用哪些知识库、是否允许查询通用知识、
是否允许执行运维任务。DeepSeek/Harness 开关、Kubernetes Context、Namespace、模型温度、
召回数量等只由管理员在助手配置中决定。

### 助手欢迎页

`GET /api/assistants/{id}/welcome` 返回：能做什么、不能做什么、推荐问题、可访问资料范围、
最近热门问题、是否允许通用知识与运维。前端在问答空状态展示。

### Mac 验收

```bash
COMPANY_SEARCH_TEST_DATABASE_URL="postgresql+psycopg://company_search:company_search@127.0.0.1:54329/company_search_test" \
  backend/.venv/bin/python -m pytest backend/tests/test_p1_permission_integration.py -k "p3" -v
```

手工步骤：进入“助手配置”新建助手并设置答案模板与无答案策略；在问答页切换到该助手，
确认顶部只显示“仅内部资料/可查通用知识/可执行运维任务”等用户可见信息，空状态展示能力与最近热门问题。

## P2-4 轻量 Chatflow

第一版不做自由拖拽，用**固定画布**配置节点与分支，入口在“系统管理 → 流程”（`ASSISTANT_MANAGE`）。

### 节点

开始、问题分类、问题改写（含上下文补全/Multi-query）、知识库检索、Reranker 精排、条件判断、
本地模型、DeepSeek、Harness 运维、答案校验、缺失知识提示、最终回答。

### 基础能力

- 节点输入/输出变量：每个节点把结果写入运行上下文，供后续节点引用。
- 节点启用/停用：停用节点不参与执行；绑定 Chatflow 的助手以节点开关为准。
- 条件分支：条件节点按 `branches` 的 `when` 命中或 `default_next` 跳转。
- 失败处理与超时：节点失败按 `on_error` 跳转，否则终止；生成节点可配置 `timeout_seconds`。
- 调试运行：`POST /api/chatflows/{id}/debug` 按图执行并返回每个节点的状态、耗时与输出摘要。
- 每个节点耗时：运行记录写入 `chat_messages.metrics.node_timings`，调试面板与检索实验室展示。
- 草稿/发布/回滚：草稿与发布版本分离；发布生成版本快照，可回滚任意历史版本。
- 助手绑定：每个助手可绑定一个流程；未绑定时使用内置默认流程。

### 推荐默认流程

开始 → 问题分类 → 上下文补全 → Multi-query → 权限过滤 → 混合检索 → Reranker → 置信度判断
（资料充分 → 本地千问 → 引用校验 → 回答；资料不足且允许 DeepSeek → DeepSeek → 标记通用知识；
运维任务 → Harness → 人工确认；无法回答 → 缺失知识提示）。

### Mac 验收

```bash
COMPANY_SEARCH_TEST_DATABASE_URL="postgresql+psycopg://company_search:company_search@127.0.0.1:54329/company_search_test" \
  backend/.venv/bin/python -m pytest backend/tests/test_p2_chatflow_unit.py backend/tests/test_p1_permission_integration.py -k "p4" -v
```

手工步骤：进入“系统管理 → 流程”，停用 Reranker 节点并保存草稿 → 发布版本 → 运行调试查看每个
节点耗时 → 回滚历史版本 → 在“助手配置”把该流程绑定到助手，确认问答按节点开关执行。

## P2-5 用户体验与比赛展示

### 回答过程可视化

问答过程中推送 `stage` 事件：正在理解问题 → 正在改写检索问题 → 正在检索 N 个知识库 →
找到 N 个候选片段 → 正在筛选最相关资料 → 正在组织答案 → 正在核对引用。普通用户只看简要状态，
管理员可在检索实验室/问答追踪中展开完整调试信息。

### 流式输出优化

- 尽早返回首字（SSE 增量输出）、检索与模型请求支持取消（停止生成）。
- 切换页面继续生成（KeepAlive），刷新后恢复会话与“已中断可重新生成”状态。
- 防止重复提交（生成中禁用输入）；指标区分 `retrieval_ms` 与 `llm_generation_ms`。

### 推荐追问

回答完成后返回 2~4 个推荐追问（默认启发式，可开启本地模型生成），点击即可继续提问。

### 答案操作

复制、重新生成、导出 Markdown、导出 PDF（浏览器打印）、有帮助/没帮助、原因选择、补充反馈、
举报敏感或错误答案。

### 知识缺口中心

自动记录未找到答案、低置信度、用户“没帮助”、引用/文档不正确、有资料但无权访问的问题；
管理员可指派负责人、关联正确文档、补充说明、重新运行并对比修复前后答案。
入口在“系统管理 → 知识缺口”（`STATS_VIEW`）。

### 首页数据展示

新增首页（登录即可查看）：知识库数量、文档数量、可检索片段、今日问答、平均响应时间、
引用覆盖率、用户满意度、热门问题、知识缺口数量。

### Mac 验收

```bash
COMPANY_SEARCH_TEST_DATABASE_URL="postgresql+psycopg://company_search:company_search@127.0.0.1:54329/company_search_test" \
  backend/.venv/bin/python -m pytest backend/tests/test_p2_ux_unit.py backend/tests/test_p1_permission_integration.py -k "p5" -v
```

手工步骤：登录后进入首页查看聚合数据；提问时观察状态推进与推荐追问；对回答点踩或举报，
进入“系统管理 → 知识缺口”处理并重新运行对比。

## P2-6 文档理解能力

### 高质量 PDF 解析

PDF 解析器（版本 2）在文字层基础上增加：按字号识别**标题层级**、跨页重复行的**页眉页脚去除**、
**多栏排版**排序、`find_tables()` **表格提取**、**图注关联**（图/表/Figure 前缀块）、
扫描页 **OCR 回退**、页码映射与**重复段落清理**。

### Office 解析增强

- DOCX：标题层级、表格结构化、**合并单元格去重**、内嵌图片 OCR。
- PPTX：标题、文本框、表格、备注与图片 OCR。
- XLSX：按工作表、**合并单元格填充**、内嵌图片 OCR；CSV 保留行级位置。

### 切片策略配置（按知识库）

`knowledge_bases.chunking_config` 支持策略：固定长度、标题层级、段落、页面、表格、父子切片，
以及 `target` / `maximum` / `overlap` / `min_chars` / `row_batch`（超长表格按行批次分块）。
父子切片会写入父片段与子片段（`chunk_role` / `parent_sequence_number`）。

`POST /api/documents/{id}/chunk-preview` 可在**不写入数据库**的前提下预览切片效果，并临时覆盖配置；
前端“资料库 → 详情”提供“预览切片效果”。

### 文档标签与知识图谱基础数据

文档新增 `author`、`department_id`、`topic`、`related_document_ids` 与有效期
（`valid_from` / `valid_until`），配合已有标签、版本关系，为后续实体关系检索保留数据。

### Mac 验收

```bash
COMPANY_SEARCH_TEST_DATABASE_URL="postgresql+psycopg://company_search:company_search@127.0.0.1:54329/company_search_test" \
  backend/.venv/bin/python -m pytest backend/tests/test_p2_document_understanding.py backend/tests/test_p1_permission_integration.py -k "p6" -v
```

手工步骤：在“管理知识库”为某库选择切片策略并保存 → 上传文档 → 在文档详情点击“预览切片效果”
查看片段长度与位置 → 填写作者/部门/主题/关联文档并保存。

## 说明

- 所有批次已分别提交：P1-1/2（会话+页面）、P1-3（性能）、P1-4（助手）、P1-5（账号权限）、
  P1-8（审计/外发控制）、P1-6（反馈）、P1-7（统计）、P2-0（评测集与检索配置版本）、
  P2-1（Query Rewrite、多查询、精排、元数据过滤、中文词典）、
  P2-2（置信度、引用校验、无答案处理、可追溯引用、答案模板）、
  P2-3（助手角色配置、预置助手、用户端信息收敛、欢迎页）、
  P2-4（固定画布流程、节点开关、调试运行、版本发布与回滚、助手绑定）、
  P2-5（过程可视化、流式优化、推荐追问、答案操作、知识缺口中心、首页数据）、
  P2-6（PDF/Office 解析增强、切片策略配置与预览、文档图谱元数据）。
