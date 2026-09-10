# Company Search 后端接口手册

本文面向需要调用或继续开发后端的同事。后端默认监听 `http://127.0.0.1:8000`，所有业务接口均以 `/api` 开头。

## 在线接口文档

FastAPI 根据路由、Pydantic 模型和类型注解自动生成 OpenAPI 文档：

- Swagger UI：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`

Swagger UI 中可以展开接口、点击 **Try it out** 并直接发送请求。所有 `/api/*`（除登录、健康检查等公开端点）都需要携带登录会话 Cookie；仅监听本机地址，不应直接暴露到公网。当前版本已提供本地账号、功能级 RBAC 与文档 ACL。

## 统一错误格式

业务错误使用对应的 HTTP 状态码，并返回：

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "文档不存在",
    "details": null
  }
}
```

常见状态码：`400` 参数或文件无效、`401` 未登录、`403` 无功能权限（`PERMISSION_DENIED`）或无权访问文档、`404` 文档不存在、`409` 内容重复或正在处理、`413` 文件超过 200 MB、`415` 文件类型不支持、`422` 请求字段校验失败、`500` 未预期的内部错误。

功能权限不足时返回 `403`，`code` 为 `PERMISSION_DENIED`，`details.permission` 为缺少的权限码：

```json
{
  "error": {
    "code": "PERMISSION_DENIED",
    "message": "当前账号没有此功能权限",
    "details": { "permission": "DOCUMENT_UPLOAD" }
  }
}
```

## 健康检查

### `GET /api/health`

确认 FastAPI 进程可以响应。

```bash
curl http://127.0.0.1:8000/api/health
```

返回 `{"status":"ok"}`。这个接口不检查 OCR、Ollama 或 DeepSeek。

## 认证与功能权限

- `POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/auth/me`、`GET /api/health` 为公开端点（`/api/auth/me` 未登录返回 `authenticated=false`）。
- `GET /api/auth/me` 返回当前用户的 `roles` 与 `permissions`（有效权限码，超级管理员为全部）。
- 除公开端点外，所有 `/api/*` 需要有效会话 Cookie，否则返回 `401 AUTH_REQUIRED`。
- 关键接口按功能权限校验，无权限返回 `403 PERMISSION_DENIED`；功能权限与文档 ACL 同时生效。
- 权限码、默认角色与完整接口映射见 [P1 升级说明](p1-upgrade-guide.md#功能级-rbac0018)。

## 文档接口

### `POST /api/documents/upload`

使用 `multipart/form-data` 上传一个文件，字段名必须是 `file`。

```bash
curl -F 'file=@/绝对路径/日报汇总.txt' \
  http://127.0.0.1:8000/api/documents/upload
```

成功返回 `201` 和文档元数据。上传成功只表示原文件已安全保存且解析任务已入队；后台 Worker 会继续让状态经过 `PENDING`、`PARSING`、`CHUNKING`、`PARSED`、`EMBEDDING`、`INDEXING`，最后到达可检索的 `READY`。相同内容由 SHA-256 判断，重复上传返回 `409 DUPLICATE_DOCUMENT`。

### `GET /api/documents`

分页查询资料库。可选查询参数：

| 参数 | 含义 | 默认值 |
| --- | --- | --- |
| `query` | 文件名模糊匹配 | 无 |
| `extension` | 扩展名，如 `pdf`、`docx` | 无 |
| `status` | 文档处理状态 | 无 |
| `page` | 页码，从 1 开始 | `1` |
| `page_size` | 每页数量，1～100 | `25` |

```bash
curl 'http://127.0.0.1:8000/api/documents?extension=pdf&page=1&page_size=25'
```

响应中的 `items` 是文档数组，`total` 是符合条件的总数。

### `GET /api/documents/{document_id}`

查询单个文档元数据、处理状态、解析器和失败原因。

### `GET /api/documents/{document_id}/content`

分页读取解析后存入 PostgreSQL 的文本片段。参数为 `page` 和 `page_size`。片段可能包含 `page_start`、`slide_number`、`sheet_name`、`row_start`、`section_path` 和 `ocr_confidence`，用于定位原文。

```bash
curl 'http://127.0.0.1:8000/api/documents/文档UUID/content?page=1&page_size=25'
```

### `GET /api/documents/{document_id}/download`

下载磁盘中保存的原始附件。解析、检索和问答不会通过这个接口读取附件。

### `POST /api/documents/{document_id}/reprocess`

重新创建解析任务。适用于 OCR 环境修复、解析器升级或先前处理失败的文档。

### `DELETE /api/documents/{document_id}`

删除文档元数据、文本片段、处理任务及磁盘原文件。成功返回 `204`，无响应正文。

## 混合检索

### `POST /api/search`

同时执行 PostgreSQL 全文关键词召回和 pgvector 语义召回，再使用 RRF 合并排名。只检索状态为 `READY` 的文档。

```bash
curl -X POST http://127.0.0.1:8000/api/search \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "Kubernetes 部署流程",
    "extension": "docx",
    "document_name": null,
    "created_from": null,
    "created_to": null,
    "limit": 10
  }'
```

结果中的 `match_type` 为 `keyword`、`vector` 或 `hybrid`，分别表示关键词命中、语义命中或两路同时命中。`content` 已来自数据库中的解析片段，检索时不会重新读取附件。

P2-1 起支持结构化元数据过滤（权限过滤始终先执行）：

```json
{
  "query": "Kubernetes 部署流程",
  "knowledge_base_id": "…",
  "extension": "docx",
  "tags": ["运维"],
  "department_id": "…",
  "owner_user_id": "…",
  "created_from": "2026-01-01",
  "created_to": "2026-12-31",
  "relative_path": "技术部/",
  "version_number": 2,
  "document_status": "READY",
  "valid_only": true,
  "limit": 10
}
```

当默认检索配置版本开启 Query Rewrite / Multi-query 时，服务会先做上下文补全与查询改写，
再分别召回并做 RRF 融合；`diagnostics.queries` 返回实际使用的检索表达，`diagnostics.retrieval_query`
返回改写后的主查询。`SearchResult` 额外返回 `pre_rerank_rank` / `post_rerank_rank`（重排前后名次）。

## RAG 知识问答

### `GET /api/answer/status`

返回 Ollama 是否可访问、配置的千问模型是否已安装，以及 DeepSeek 是否配置。

```bash
curl http://127.0.0.1:8000/api/answer/status
```

### `POST /api/answer/stream`

先检索内部片段，再让本地千问根据片段生成带 `[n]` 引用的答案。`use_deepseek=true` 时才会尝试把问题、内部片段和千问初稿发送给 DeepSeek。接口响应类型为 `text/event-stream`。

```bash
curl -N -X POST http://127.0.0.1:8000/api/answer/stream \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "公司的 Kubernetes 服务如何部署？",
    "use_deepseek": false,
    "history": [],
    "extension": null,
    "document_name": null,
    "created_from": null,
    "created_to": null
  }'
```

SSE 每个消息包含 `event:` 类型和 `data:` JSON。可能出现：

| 事件 | 说明 |
| --- | --- |
| `stage` | 当前处于检索、本地生成或 DeepSeek 增强阶段 |
| `query_rewrite` | P2-1：原始问题、补全后问题、实际检索问题与多查询列表 |
| `sources` | 本次回答使用的内部片段和引用编号 |
| `delta` | 追加到页面的答案文本 |
| `replace` | 清空当前答案，接下来用增强/修正后的答案替换 |
| `warning` | DeepSeek 未配置或远端失败等可降级问题 |
| `confidence` | P2-2：答案置信度分级（`HIGH`/`MEDIUM`/`INSUFFICIENT`）与原因 |
| `citation_check` | P2-2：引用校验结果（无效编号、缺少依据的句子、不可访问引用） |
| `no_answer` | P2-2：无答案/低置信度归因、固定提示、推荐资料与后续操作 |
| `done` | 正常结束，包含 provider、scope 和来源数量 |
| `error` | 本地模型等关键步骤失败，无法继续回答 |

典型本地流程是 `stage(retrieving) → sources → stage(local_generating) → delta... → done`。DeepSeek 增强成功时会继续出现 `stage(deepseek_enhancing) → replace → delta... → done`。P2-2 在生成结束后追加 `confidence` / `citation_check`，资料不足时追加 `no_answer` 并用固定提示替换答案（缺少依据的句子标记为“推断”）。

`chat_messages.metrics` 会保存 `confidence`、`citation_check`、`no_answer`、`question_type` 等字段，历史引用接口额外返回 `version_number`、`matched_keywords`、`can_download`、`extension` 供追溯展示。

`scope` 表示答案依据：`INTERNAL` 为较明确的内部资料，`INTERNAL_LIMITED` 为有限的语义证据，`GENERAL` 为无内部资料时的 DeepSeek 通用知识，`NONE` 为未找到内部答案。DeepSeek 未配置或调用失败时会发送 `warning`，并保留千问本地答案。

## 助手接口

```text
GET    /api/assistants                 # 列出助手（任意登录用户）
GET    /api/assistants/{id}            # 助手详情
GET    /api/assistants/{id}/welcome    # 欢迎页：能力/限制/资料范围/最近热门问题
POST   /api/assistants                 # 新建（ASSISTANT_MANAGE）
PATCH  /api/assistants/{id}            # 编辑（ASSISTANT_MANAGE）
POST   /api/assistants/{id}/enable|disable
PUT    /api/assistants/{id}/knowledge-bases
DELETE /api/assistants/{id}
```

助手可配置 `answer_template`（`AUTO`/`POLICY`/`TECHNICAL`/`PROGRESS`/`COMPARISON`/`SUMMARY`/`GENERAL`）、
`no_answer_policy`（`SUGGEST`/`STRICT`/`GENERAL`）、`internet_enabled`、`capabilities`、`limitations`，
以及知识库范围、召回数量、温度、DeepSeek/Harness 策略。问答请求只需传 `assistant_id`，
运行策略由服务端助手配置决定，用户端不展示这些技术选项。

`GET /api/assistants/{id}/welcome` 返回：能做什么、不能做什么、推荐问题、可访问资料范围
（`knowledge_scope`）、最近热门问题、是否允许通用知识（`general_knowledge_allowed`）与
运维任务（`operations_allowed`，仅管理员为 true）。

## 文档理解与切片

按知识库配置切片策略（`chunking_config`，随 `POST/PATCH /api/knowledge-bases` 提交）：

```json
{
  "strategy": "parent_child",
  "target": 800,
  "maximum": 1200,
  "overlap": 100,
  "min_chars": 40,
  "row_batch": 30
}
```

`strategy` 可选：`fixed` / `heading` / `paragraph` / `page` / `table` / `parent_child`。
表格策略按 `row_batch` 行分块，避免超长表格生成过大片段。

切片预览（不写入数据库，可临时覆盖配置）：

```text
POST /api/documents/{id}/chunk-preview
body: { "chunking_config": {...}?, "limit": 50 }
```

文档图谱元数据（随 `PATCH /api/documents/{id}` 提交）：`author`、`department_id`、`topic`、
`related_document_ids`、`valid_from`、`valid_until`；响应同样返回这些字段。

## 首页与知识缺口

首页看板（登录即可查看，仅汇总计数）：

```text
GET /api/stats/dashboard
```

返回：知识库数量、文档数量、可检索片段、今日问答、平均响应时间、引用覆盖率、用户满意度、
热门问题、知识缺口数量。

知识缺口中心（`STATS_VIEW`）：

```text
GET   /api/knowledge-gaps?status=&reason=&assignee_user_id=
GET   /api/knowledge-gaps/statistics
GET   /api/knowledge-gaps/{id}
PATCH /api/knowledge-gaps/{id}          # 状态/负责人/关联文档/说明
POST  /api/knowledge-gaps/{id}/rerun    # 重新运行并返回修复前后对比
```

未答、低置信度、点踩与“引用不正确”会自动进入知识缺口中心（去重累加）。

## 流程接口（Chatflow）

全部需要 `ASSISTANT_MANAGE` 权限。

```text
GET    /api/chatflows
POST   /api/chatflows
GET    /api/chatflows/node-types
GET    /api/chatflows/{id}
PATCH  /api/chatflows/{id}                 # 保存草稿（名称/描述/图/启停）
DELETE /api/chatflows/{id}
POST   /api/chatflows/{id}/publish         # 发布草稿为新版本
POST   /api/chatflows/{id}/rollback        # 回滚到指定历史版本
GET    /api/chatflows/{id}/versions
GET    /api/chatflows/{id}/versions/{version}
POST   /api/chatflows/{id}/debug           # 调试运行，返回逐节点耗时/状态/输出
```

图结构为固定画布：`{"start_node_id": "start", "nodes": [{id,type,name,enabled,config,next}]}`；
条件节点用 `config.branches`（`when` → `next`）与 `config.default_next` 分支。助手通过
`chatflow_id` 绑定已发布流程，问答时按节点开关执行，并把逐节点耗时写入
`chat_messages.metrics.node_timings`。

## 批量导入接口

`POST /api/batches` 创建批次并登记完整文件清单；请求包括 `name`、可选的 `category/tags/note`，以及包含 `relative_path/original_name/size_bytes` 的 `files` 数组。预先登记清单使浏览器中断后仍能识别未上传文件。

`POST /api/batches/{batch_id}/files` 使用表单字段 `relative_path` 和 `file` 上传单个批次文件。内容重复时关联已有文档并返回 `DUPLICATE`，不会重复解析。

```text
GET  /api/batches
GET  /api/batches/{batch_id}
POST /api/batches/{batch_id}/files/{file_id}/retry
POST /api/batches/{batch_id}/files/{file_id}/ignore
POST /api/batches/{batch_id}/cancel
```

批次详情分别返回上传和处理状态。只有处理状态为 `INDEXED` 的文件可参与检索。

## Agent Harness

`POST /api/answer/stream` 可增加 `use_harness`、`k8s_context` 和 `k8s_namespace`。关闭时沿用普通 RAG；打开后通过 SSE 返回 `harness_started`、`tool_requested`、`tool_running`、`tool_result`、`approval_required` 和 `harness_done`。

```text
GET  /api/harness/status
GET  /api/harness/namespaces?context=docker-desktop
GET  /api/harness/tasks/{task_id}
POST /api/harness/tasks/{task_id}/resume
POST /api/harness/approvals/{approval_id}/confirm
POST /api/harness/approvals/{approval_id}/reject
```

确认接口只接受 `{"confirmation_context":"完整context名称"}`。操作内容从服务端审批记录重新读取，前端不能在确认时替换参数。YAML 部署仅允许应用资源白名单，并且必须先通过 server-side dry-run 和 diff。

## 代码入口与请求链路

- `backend/app/main.py`：相当于 PHP 项目的应用入口和框架启动配置，创建常驻的 ASGI 应用。
- `backend/app/api/`：类似 Controller，接收 HTTP 参数并调用服务。
- `backend/app/schemas/`：类似 DTO/请求校验对象，同时生成 OpenAPI 字段定义。
- `backend/app/services/`：业务逻辑，包括上传、解析、检索和 RAG 编排。
- `backend/app/models/`：SQLAlchemy ORM 数据表映射。
- `backend/app/worker.py`：独立后台任务进程。

一次普通请求的方向是：`浏览器 → Uvicorn/FastAPI → api 路由 → service → SQLAlchemy/PostgreSQL 或受管文件目录 → Pydantic 响应`。

## Nginx 与 SSE 注意事项

本地开发由 Uvicorn 直接监听 `127.0.0.1:8000`，不需要 Nginx。生产环境通常由 Nginx 负责 HTTPS、域名、访问控制和反向代理。问答接口使用 SSE，代理 `/api/answer/stream` 时需要关闭响应缓冲，否则浏览器可能等到完整答案生成后才一次性显示：

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 300s;
}
```

当前本地版已实现本地账号认证、功能级 RBAC、文档 ACL、登录限流与审计日志；生产部署仍应补充 HTTPS、访问控制与更严格的速率限制。

## P0 知识治理接口

知识库：

```text
GET   /api/knowledge-bases
POST  /api/knowledge-bases
PATCH /api/knowledge-bases/{id}
POST  /api/knowledge-bases/{id}/enable
POST  /api/knowledge-bases/{id}/disable
```

`POST /api/documents/upload` 增加可选表单字段 `knowledge_base_id`；批次创建 JSON 同样支持该字段。`GET /api/documents` 支持 `knowledge_base_id`、`tag` 和 `deleted=true`。

```text
PATCH  /api/documents/{id}              修改知识库、路径、标签和元数据
POST   /api/documents/{id}/enable       允许参与检索
POST   /api/documents/{id}/disable      停止参与检索
POST   /api/documents/{id}/restore      从回收站恢复
DELETE /api/documents/{id}/purge        永久删除回收站资料
GET    /api/documents/{id}/versions     查看版本关系
GET    /api/documents/{id}/chunks       查看可治理片段
PATCH  /api/chunks/{id}                 修改内容并原子重建索引
POST   /api/chunks/{id}/enable
POST   /api/chunks/{id}/disable
POST   /api/chunks/{id}/reindex
POST   /api/chunks/{id}/restore-original
```

普通 `DELETE /api/documents/{id}` 现在只执行软删除。资料一旦软删除或停用，统一检索服务会让资料检索、知识问答和 Harness 同时排除它。

## 检索实验室接口

全部需要 `RETRIEVAL_LAB_USE` 权限。

诊断（可选传入最近对话以演示上下文补全）：

```text
POST   /api/retrieval-lab/inspect   # body: query, knowledge_base_id?, limit?, history?
```

中文检索词典（管理员维护同义词/缩写/专有名词）：

```text
GET    /api/retrieval-lab/dictionaries?category=&enabled=
POST   /api/retrieval-lab/dictionaries
PATCH  /api/retrieval-lab/dictionaries/{id}
DELETE /api/retrieval-lab/dictionaries/{id}
```

评测集与标准问题：

```text
GET    /api/retrieval-lab/evaluation-sets
POST   /api/retrieval-lab/evaluation-sets
GET    /api/retrieval-lab/evaluation-sets/{id}
PATCH  /api/retrieval-lab/evaluation-sets/{id}
DELETE /api/retrieval-lab/evaluation-sets/{id}
GET    /api/retrieval-lab/evaluation-sets/{id}/cases
POST   /api/retrieval-lab/evaluation-sets/{id}/cases
POST   /api/retrieval-lab/evaluation-sets/{id}/import   # multipart CSV/Excel
PATCH  /api/retrieval-lab/cases/{id}
DELETE /api/retrieval-lab/cases/{id}
```

检索配置版本：

```text
GET    /api/retrieval-lab/config-versions
POST   /api/retrieval-lab/config-versions
GET    /api/retrieval-lab/config-versions/{id}
PATCH  /api/retrieval-lab/config-versions/{id}
DELETE /api/retrieval-lab/config-versions/{id}
GET    /api/retrieval-lab/config-versions/compare?left=&right=
```

运行与对比：

```text
POST   /api/retrieval-lab/runs            # body: evaluation_set_id, config_version_id?, limit?, include_answers?
GET    /api/retrieval-lab/runs?evaluation_set_id=
GET    /api/retrieval-lab/runs/{id}
GET    /api/retrieval-lab/runs/compare?left=&right=
```

`inspect` 返回规范化问题、扩展词、实际模式、降级提示、耗时，以及关键词、向量、RRF、精排和最终上下文各阶段候选；开启改写时额外返回 `query_rewrite`（原始问题、补全后问题、实际检索问题、是否使用上下文）与 `queries`（多查询列表）。运行记录保存配置快照与逐用例明细；`runs/compare` 返回指标变化、配置差异与逐用例变化。CSV/Excel 导入表头支持中英文别名，文档列可用 UUID 或文件名。
