# 本地 Agent Harness 设计规格

## 1. 目标

在现有公司知识问答中增加可选的轻量 Agent Harness。Harness 关闭时完全保持当前固定 RAG 流程；打开时由本地 `qwen3:8b` 选择白名单工具，Harness 校验、执行、审计工具调用，并对所有 Kubernetes 写操作实施逐次人工审批。

第一版同时支持公司资料检索、Kubernetes/日志只读查询，以及重启、扩缩容、回滚、镜像更新和 YAML 部署。DeepSeek 只可增强最终答案，不能决定或发起工具调用。

## 2. 总体架构

新增独立 `HarnessService`，不把 Agent 循环和 Kubernetes 逻辑继续堆入 `RagService`。现有检索能力包装为 `CompanySearchTool`；Kubernetes 能力由只读和写入工具实现；审批与审计分别由独立服务负责。

```text
Answer API
  ├── Harness 关闭 → 现有 RagService → 千问 → 可选 DeepSeek
  └── Harness 打开 → HarnessService
                        ├── qwen3:8b 决策循环
                        ├── CompanySearchTool
                        ├── KubernetesReadTools
                        ├── KubernetesWriteTools
                        ├── ApprovalService
                        └── AuditService
```

Harness 每个任务最多执行 8 步，总运行时间最多 5 分钟。模型只能返回结构化的 `call_tool` 或 `final_answer` 决策；Harness 不执行模型生成的 Shell 文本。

## 3. 页面模式与模型分工

知识问答页面增加“使用 Harness”开关，默认关闭。

- 关闭：请求沿用当前检索、千问回答和可选 DeepSeek 增强流程；新增字段不改变旧行为。
- 打开：页面显示 Kubernetes context 和 namespace 选择器，并展示工具执行时间线。
- 本地 `qwen3:8b`：理解目标、选择只读工具、提出写操作申请、根据工具结果生成答案。
- DeepSeek：仅在原有开关开启且配置有效时增强最终答案；不得返回工具调用。
- DeepSeek 未配置或失败：保留本地 Harness 答案并展示警告。

模型决策协议：

```json
{
  "action": "call_tool",
  "tool": "k8s_get_pods",
  "arguments": {
    "context": "production",
    "namespace": "default",
    "selector": "app=go-demo"
  },
  "reason": "需要确认服务对应 Pod 的当前状态"
}
```

`action` 只允许 `call_tool` 或 `final_answer`。参数由各工具的 Pydantic Schema 校验。格式错误时最多让千问修正 2 次，仍失败则终止工具循环，返回已有信息和明确错误。

## 4. 工具目录

### 4.1 自动执行的只读工具

- `company_search`：复用当前混合检索和引用信息。
- `k8s_list_namespaces`：列出 namespace。
- `k8s_get_workloads`：查询 Deployment、StatefulSet、DaemonSet 和 Pod。
- `k8s_describe_resource`：读取资源详情、状态和事件。
- `k8s_get_pod_logs`：默认最近 200 行，最大 1000 行。
- `k8s_get_events`：查询 Kubernetes 事件。
- `k8s_get_rollout_status`：查询发布状态。
- `k8s_get_resource_yaml`：读取当前资源；Secret 内容必须屏蔽且不得提供给模型。

### 4.2 每次必须审批的写工具

- `k8s_restart_deployment`
- `k8s_scale_workload`
- `k8s_rollback_deployment`
- `k8s_update_image`
- `k8s_apply_yaml`

不提供删除工具，不提供任意 Shell 工具。

### 4.3 YAML 资源白名单

允许 namespace 级应用资源：

- Deployment、StatefulSet、DaemonSet
- Service、Ingress
- ConfigMap
- Job、CronJob
- HorizontalPodAutoscaler

拒绝 Secret、Namespace、Node、RBAC、CRD、Admission Webhook、PersistentVolume、其他集群级资源和未知资源种类。单次 YAML 最大 1 MiB、最多 20 个资源。

## 5. Kubernetes 接入与安全边界

允许的 context 由 `backend/.env` 配置：

```env
COMPANY_SEARCH_K8S_ALLOWED_CONTEXTS=docker-desktop,dev-cluster,production
```

页面只能选择配置白名单中的 context。选定 context 后允许读取和写入该集群全部 namespace；模型不能覆盖或拼接额外 `--context`。后端通过参数数组调用 `kubectl`，禁止 `shell=True`。

只读工具默认超时 30 秒；写操作默认超时 5 分钟。每次调用前重新校验 context、namespace、工具和参数。Kubernetes 输出、事件和 Pod 日志均视为不可信数据，只作为工具结果传入模型，不得覆盖系统规则或工具策略。

## 6. 写操作审批流程

所有写操作逐次审批，不支持一次授权后连续执行。

```text
千问提出写操作
→ Harness 校验白名单和参数
→ kubectl server-side dry-run
→ 读取当前资源并生成差异
→ PostgreSQL 创建 PENDING 审批
→ SSE 返回 approval_required 并结束当前连接
→ 页面展示 context、namespace、目标、YAML/镜像变更和差异
→ 用户输入完整 context 名称
→ 确认或拒绝
→ 后端校验审批有效期及 resourceVersion
→ 执行真实写操作
→ 查询资源或 rollout 状态
→ 保存结果并恢复 Harness 任务
→ 千问生成总结
```

所有 YAML 部署必须通过 `kubectl apply --dry-run=server` 和差异预览。审批默认 10 分钟过期。确认前若目标资源的 `resourceVersion` 已变化，审批立即失效，必须重新生成 dry-run 和差异。

第一版采用本地单用户身份：审计操作者为 `local-user`。确认按钮只有在用户输入的 context 名称与审批目标完全一致时可用。

## 7. API 与 SSE 契约

现有 `POST /api/answer/stream` 请求扩展为：

```json
{
  "question": "检查 go-demo 并部署新镜像",
  "use_harness": true,
  "use_deepseek": false,
  "k8s_context": "production",
  "k8s_namespace": "default",
  "history": []
}
```

新增接口：

```text
GET  /api/harness/status
GET  /api/harness/namespaces?context=...
GET  /api/harness/tasks/{task_id}
POST /api/harness/tasks/{task_id}/resume
POST /api/harness/approvals/{approval_id}/confirm
POST /api/harness/approvals/{approval_id}/reject
```

审批确认请求包含用户输入的 context 名称；后端不能信任前端传回的操作参数，必须从审批记录重新加载经过 dry-run 的原始请求。

SSE 在现有事件基础上增加：

- `harness_started`：任务编号、context、namespace 和执行限制。
- `tool_requested`：模型申请的工具和展示原因。
- `tool_running`：校验通过并开始执行。
- `tool_result`：截断后的工具结果摘要。
- `approval_required`：写操作审批编号、预检和差异。
- `approval_result`：确认、拒绝、过期或执行失败。
- `harness_done`：最终状态和步骤统计。

遇到待审批写操作时保存状态并结束当前 SSE，不占用连接等待。确认后前端调用 `resume` 继续；页面刷新后通过任务接口恢复待审批状态。

## 8. 数据模型与保留策略

新增三张表：

- `harness_tasks`：问题、context、namespace、状态、模型、当前步骤、最大步骤、截止时间、创建和完成时间。
- `harness_steps`：任务、序号、模型决策、工具、参数、结果摘要、耗时、状态和错误。
- `harness_approvals`：任务和步骤、操作类型、完整 YAML、SHA-256、dry-run、差异、目标 resourceVersion、确认文本、决定、操作者和执行结果。

工具输出和 Pod 日志入库前截断；完整部署 YAML 与哈希保留。审计数据默认保存 30 天，由后台 Worker 定期清理。删除审计数据不删除公司文档和 Kubernetes 资源。

## 9. 前端行为

- DeepSeek 开关旁增加 Harness 开关。
- Harness 开启后加载允许的 context，并根据选中 context 加载 namespace。
- 每个问答回合展示 Harness 时间线、工具名称、执行状态、耗时和结果摘要。
- 写操作以高风险审批卡片显示目标环境、资源、变更、dry-run 和差异。
- 用户必须输入 context 名称后才能确认；可以拒绝、停止或等待过期。
- 页面明确展示 `local-user` 的决定和执行结果。
- Harness 关闭后隐藏环境选择和工具时间线，保持现有页面行为。

## 10. 错误与降级

- `kubectl` 不存在、context 不可用、权限不足或超时：记录失败，仅返回错误，不改变集群。
- 工具参数、模型协议或 YAML 校验失败：不执行工具；协议最多修正 2 次。
- dry-run 或差异生成失败：不能创建可确认的执行申请。
- 审批拒绝、过期或资源已变化：不执行写操作，把结果返回千问总结。
- Harness 达到 8 步或 5 分钟：停止调用工具，用已有结果结束回答。
- Harness 故障不影响关闭 Harness 后的原有 RAG。

## 11. 验收与验证

服务器开发环境只生成代码并执行语法、类型契约和差异等静态检查，不运行单元测试或前端测试。提供 Mac 本地验证说明，覆盖：

1. Harness 关闭时原有 RAG 行为不变。
2. Harness 打开后能够自动检索公司资料并显示步骤。
3. 能查询 Pod、工作负载、事件、rollout 和日志。
4. 未配置 context、缺少 `kubectl`、无权限和超时均安全失败。
5. 所有写操作都停在审批阶段，不能自动执行。
6. context 确认文字错误时拒绝执行。
7. YAML 未通过 dry-run、超限或资源种类不在白名单时拒绝。
8. 确认后可完成重启、扩缩容、回滚、镜像更新和 YAML apply。
9. 审批拒绝、过期、刷新恢复和 resourceVersion 变化正确处理。
10. DeepSeek 开关无论开关都不能发起工具操作。
11. PostgreSQL 产生完整审计记录，并可按 30 天策略清理。

## 12. 明确不做

- 不允许模型执行任意 Shell 命令。
- 不提供 Kubernetes 删除操作。
- 不操作集群级资源和敏感资源。
- 不新增账号系统；第一版仅为 `127.0.0.1` 本地单用户。
- 不让 DeepSeek 参与工具规划或审批。
- 不自动执行任何 Kubernetes 写操作。
