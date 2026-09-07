# Local Agent Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为现有本地公司知识问答增加可选、可审计、所有 Kubernetes 写操作逐次人工审批的轻量 Agent Harness。

**Architecture:** 保留 `RagService` 作为 Harness 关闭时的固定问答链；新增独立 Harness 编排、严格工具注册表、Kubernetes 客户端、持久化任务/步骤/审批和恢复接口。由本地 `qwen3:8b` 产生结构化决策，Python 只执行白名单工具，DeepSeek 仅增强最终答案。

**Tech Stack:** Python 3.12/3.13、FastAPI、Pydantic、SQLAlchemy、PostgreSQL、Ollama HTTP API、Vue 3、TypeScript、SSE、macOS `kubectl`。

**Spec:** `docs/superpowers/specs/2026-09-07-local-agent-harness-design.md`

## Global Constraints

- Harness 默认关闭；关闭时现有 `/api/answer/stream` 行为不变。
- 所有 Kubernetes 写操作每次必须由 `local-user` 输入目标 context 名称确认。
- 只允许配置白名单 context；允许这些 context 下的全部 namespace。
- 禁止 `shell=True`、任意 Shell、删除资源、Secret、RBAC、CRD 和集群级资源。
- YAML apply 必须先通过 server-side dry-run 和差异预览。
- 千问负责工具决策；DeepSeek 只增强最终答案且不能调用工具。
- 每个 Harness 任务最多 8 步、5 分钟；审批 10 分钟过期；审计默认保留 30 天。
- 按用户要求，服务器不运行单元测试和前端测试，只执行静态检查并提供 Mac 验收步骤。

---

### Task 1: 配置、数据契约和持久化模型

**Files:**
- Modify: `backend/app/config.py`
- Create: `backend/app/models/harness.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/schemas/harness.py`
- Modify: `backend/app/schemas/answer.py`
- Create: `backend/migrations/versions/0004_harness.py`

**Interfaces:**
- Produces: `HarnessTask`, `HarnessStep`, `HarnessApproval` ORM 模型。
- Produces: `HarnessTaskStatus`, `HarnessStepStatus`, `ApprovalStatus` 枚举。
- Produces: Harness 状态、任务、审批确认/拒绝和扩展 SSE 的 Pydantic 模型。

- [ ] **Step 1: 扩展配置**

加入允许 context、步骤/时间限制、审批过期、审计保留、kubectl 超时和输出截断配置；`allowed_k8s_contexts` 属性负责把逗号字符串去空格并去重。

- [ ] **Step 2: 定义 ORM 状态机**

任务状态固定为 `RUNNING/AWAITING_APPROVAL/COMPLETED/FAILED/CANCELLED`；步骤状态固定为 `REQUESTED/RUNNING/SUCCEEDED/FAILED/AWAITING_APPROVAL/REJECTED/EXPIRED`；审批状态固定为 `PENDING/CONFIRMED/REJECTED/EXPIRED/FAILED/EXECUTED`。

- [ ] **Step 3: 创建 Alembic 迁移**

创建 `harness_tasks`、`harness_steps`、`harness_approvals`，设置任务到步骤/审批的级联删除、任务状态和审批到期时间索引；参数与结果使用 JSONB，完整 YAML、diff 和错误使用 Text。

- [ ] **Step 4: 扩展回答请求和 SSE 类型**

`AnswerRequest` 增加 `use_harness: bool = False`、`k8s_context: str | None`、`k8s_namespace: str | None`；`AnswerEvent.type` 加入规格中的七类 Harness 事件，并增加 `task_id/step/tool/tool_arguments/tool_result/approval` 字段。

- [ ] **Step 5: 执行静态检查并提交**

运行 `python3 -m compileall -q backend/app backend/migrations` 和 `git diff --check`，提交 `feat: add harness contracts and persistence`。

### Task 2: 千问结构化决策与工具注册表

**Files:**
- Create: `backend/app/harness/__init__.py`
- Create: `backend/app/harness/types.py`
- Create: `backend/app/harness/registry.py`
- Create: `backend/app/harness/planner.py`
- Modify: `backend/app/llm/ollama.py`

**Interfaces:**
- Produces: `ToolDefinition(name, description, arguments_model, read_only)`。
- Produces: `HarnessDecision(action, tool, arguments, reason, answer)`。
- Produces: `ToolRegistry.register/get/catalog/validate`。
- Produces: `HarnessPlanner.decide(messages, tools) -> HarnessDecision`。

- [ ] **Step 1: 定义严格决策类型**

使用 Pydantic 判别 `call_tool` 与 `final_answer`；工具参数只允许 JSON 对象；未知 action、未知工具和多余字段拒绝。

- [ ] **Step 2: 实现工具注册表**

注册表以工具名唯一索引，向模型只输出名称、中文说明、是否只读和参数 JSON Schema；执行前再次用对应 Pydantic 类型验证。

- [ ] **Step 3: 扩展 Ollama 非流式 JSON 调用**

调用 `/api/chat` 时使用 `stream=false`、`format=json`、`think=false`、`keep_alive=0`；返回文本交给 `HarnessDecision` 验证，不在客户端执行工具。

- [ ] **Step 4: 实现 Planner 修正循环**

系统提示明确工具输出不可信、禁止把日志当指令、禁止 DeepSeek 规划；解析失败把校验错误反馈给千问，最多修正 2 次，超过后抛出稳定 `HARNESS_DECISION_INVALID`。

- [ ] **Step 5: 静态检查并提交**

运行 compileall 和 diff check，提交 `feat: add local harness planner and tool registry`。

### Task 3: 公司检索工具和 Kubernetes 只读工具

**Files:**
- Create: `backend/app/harness/kubernetes.py`
- Create: `backend/app/harness/tools/company_search.py`
- Create: `backend/app/harness/tools/kubernetes_read.py`
- Create: `backend/app/harness/tools/__init__.py`

**Interfaces:**
- Produces: `KubectlClient.run(context, args, stdin=None, timeout=None) -> KubectlResult`。
- Produces: `build_tool_registry(session, settings) -> ToolRegistry`。
- Consumes: `SearchService.search(SearchRequest)`。

- [ ] **Step 1: 实现安全 kubectl 客户端**

用 `asyncio.create_subprocess_exec` 和参数数组运行 `kubectl --context <白名单>`；环境使用当前用户 kubeconfig；捕获 stdout/stderr/退出码；实施超时和最大输出截断；永不启用 shell。

- [ ] **Step 2: 实现 context 与 namespace 探测**

context 必须出现在配置白名单；namespace 参数必须为 Kubernetes DNS 名称；通过 JSON 输出解析 namespace，不解析展示文本。

- [ ] **Step 3: 包装公司资料检索**

参数为 query、可选 extension/document_name、limit；返回引用编号、文档名、位置和片段，保持当前检索阈值和 RRF 行为。

- [ ] **Step 4: 实现只读 Kubernetes 工具**

所有读取命令请求 JSON/YAML 机器格式；日志默认 200、最大 1000 行；Secret 返回前删除 `data/stringData`；结果统一包含摘要、结构化数据和截断标识。

- [ ] **Step 5: 静态检查并提交**

运行 compileall 和 diff check，提交 `feat: add read-only harness tools`。

### Task 4: Kubernetes 写操作预检与审批服务

**Files:**
- Create: `backend/app/harness/tools/kubernetes_write.py`
- Create: `backend/app/services/harness_approvals.py`
- Create: `backend/app/services/harness_audit.py`

**Interfaces:**
- Produces: `PreparedOperation`，包含工具、目标、规范化参数、YAML、SHA-256、dry-run、diff 和 resourceVersion 快照。
- Produces: `ApprovalService.prepare/confirm/reject/expire_pending`。
- Produces: `AuditService.record_step/cleanup_expired`。

- [ ] **Step 1: 实现写工具参数模型**

分别限制 restart、scale、rollback、update-image 和 apply-yaml 参数；副本数限制 `0..100`；容器名、镜像名和资源名按明确格式校验。

- [ ] **Step 2: 实现 YAML 安全解析**

增加受约束 YAML 解析依赖；拒绝大于 1 MiB、超过 20 个文档、空文档、未知 apiVersion/kind、无 namespace 和所有非白名单 kind；忽略模型提交的 context 并使用任务 context。

- [ ] **Step 3: 实现预检和差异**

apply 使用 `kubectl apply --server-side --dry-run=server -f - -o yaml`；diff 的退出码 `0` 表示无差异、`1` 表示有差异、其他表示失败。其他写工具生成明确目标预览并尽可能使用 kubectl dry-run 输出；所有操作读取目标 resourceVersion。

- [ ] **Step 4: 持久化审批**

保存规范化操作，而不是信任确认请求中的参数；审批 10 分钟过期。确认时匹配完整 context 名称、重新读取 resourceVersion、重新校验白名单，任何变化都使审批过期。

- [ ] **Step 5: 执行并审计**

确认后运行唯一对应的白名单 kubectl 参数；查询 rollout/资源状态；保存 `local-user`、时间、结果和错误。拒绝、超时或失败永不执行写命令。

- [ ] **Step 6: 静态检查并提交**

运行 compileall 和 diff check，提交 `feat: add approved kubernetes write tools`。

### Task 5: Harness 编排、恢复 API 与 SSE

**Files:**
- Create: `backend/app/services/harness.py`
- Create: `backend/app/api/harness.py`
- Modify: `backend/app/api/answer.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/worker.py`

**Interfaces:**
- Produces: `HarnessService.start(request) -> AsyncIterator[AnswerEvent]`。
- Produces: `HarnessService.resume(task_id) -> AsyncIterator[AnswerEvent]`。
- Produces: `/api/harness/status`、namespaces、task、resume、confirm、reject。

- [ ] **Step 1: 实现任务循环**

创建任务后向千问提供用户问题、只读工具、写工具和前序步骤；执行只读工具后把标记为不可信的结果送回 Planner；最多 8 步且总计 5 分钟。

- [ ] **Step 2: 实现审批暂停和恢复**

写调用只执行 prepare，保存 `AWAITING_APPROVAL` 并发出 `approval_required` 后结束 SSE。确认/拒绝接口改变审批状态；resume 从 PostgreSQL 重建消息和步骤，不依赖进程内对象。

- [ ] **Step 3: 接入回答 API**

`use_harness=false` 调用原有 `RagService.stream`；`true` 时验证 context 并调用 Harness。Harness 最终答案才可进入现有 DeepSeek 增强，DeepSeek 消息不包含工具目录。

- [ ] **Step 4: 实现状态和清理**

状态接口返回 kubectl 可用性、允许 context、默认限制；Worker 每轮以低频节流方式过期审批并清理 30 天前审计数据。

- [ ] **Step 5: 静态检查并提交**

运行 compileall 和 diff check，提交 `feat: orchestrate durable harness tasks`。

### Task 6: Harness 页面、时间线和审批卡片

**Files:**
- Modify: `frontend/src/types/answer.ts`
- Modify: `frontend/src/api/answer.ts`
- Create: `frontend/src/api/harness.ts`
- Create: `frontend/src/types/harness.ts`
- Create: `frontend/src/features/answer/HarnessTimeline.vue`
- Create: `frontend/src/features/answer/HarnessApproval.vue`
- Modify: `frontend/src/features/answer/AnswerPage.vue`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: Harness 状态、任务、审批 REST 接口和扩展 AnswerEvent。
- Produces: Harness 开关、context/namespace 选择、时间线、审批确认和恢复 UI。

- [ ] **Step 1: 增加 TypeScript 契约和 API 客户端**

与后端事件、任务和审批字段逐项一致；确认接口只发送 `confirmation_context`，拒绝接口发送可选原因。

- [ ] **Step 2: 增加模式与环境选择**

Harness 默认关闭；开启后加载状态和 context；选择 context 后加载全部 namespace；没有 kubectl/context 时禁用发送并显示明确处理提示。

- [ ] **Step 3: 渲染执行时间线**

为 requested/running/succeeded/failed/awaiting-approval 显示不同状态；默认折叠大段日志和 YAML；展示工具原因、耗时和截断提示。

- [ ] **Step 4: 实现审批卡片**

高风险样式展示 context、namespace、目标、操作类型、dry-run 和 diff；输入完整 context 才启用确认；支持拒绝、过期和执行结果。

- [ ] **Step 5: 实现 SSE 暂停恢复**

收到 `approval_required` 保存 task_id 并结束当前生成状态；确认或拒绝后调用 resume；刷新页面通过任务接口恢复当前待审批卡片。

- [ ] **Step 6: 静态检查并提交**

只运行 `git diff --check`，不在服务器运行前端测试或构建；提交 `feat: add harness controls and approval UI`。

### Task 7: 安装、文档和 Mac 验收手册

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `.env.example`
- Modify: `scripts/setup.sh`
- Modify: `README.md`
- Modify: `docs/backend-api.md`
- Create: `docs/harness-mac-verification.md`

**Interfaces:**
- Produces: context 配置说明、kubectl 探测、接口说明、安全警告和人工验证步骤。

- [ ] **Step 1: 补充依赖和配置示例**

加入受约束 YAML 解析库；示例 context 默认留空，避免自动授权本机集群；setup 只提示 kubectl 状态，不安装、不修改 kubeconfig。

- [ ] **Step 2: 更新 API 文档**

记录所有 Harness REST/SSE 契约、审批状态、curl 示例和关闭 Harness 的兼容行为。

- [ ] **Step 3: 编写 Mac 验收手册**

按设计规格 11 项场景提供逐条命令和页面预期；使用专用测试 namespace；明确不要在首次验收时选择生产 context。

- [ ] **Step 4: 最终静态验证**

运行 `python3 -m compileall -q backend/app backend/migrations`、`bash -n scripts/*.sh`、`git diff --check`；确认没有真实 kubeconfig、Secret、API Key 或生产 YAML 进入 Git。

- [ ] **Step 5: 提交**

提交 `docs: add harness setup and verification guide`。
