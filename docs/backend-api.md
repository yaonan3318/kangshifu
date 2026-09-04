# Company Search 后端接口手册

本文面向需要调用或继续开发后端的同事。后端默认监听 `http://127.0.0.1:8000`，所有业务接口均以 `/api` 开头。

## 在线接口文档

FastAPI 根据路由、Pydantic 模型和类型注解自动生成 OpenAPI 文档：

- Swagger UI：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`

Swagger UI 中可以展开接口、点击 **Try it out** 并直接发送请求。当前项目只监听本机地址，没有登录鉴权，不应直接暴露到公网。

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

常见状态码：`400` 参数或文件无效、`404` 文档不存在、`409` 内容重复或正在处理、`413` 文件超过 200 MB、`415` 文件类型不支持、`422` 请求字段校验失败、`500` 未预期的内部错误。

## 健康检查

### `GET /api/health`

确认 FastAPI 进程可以响应。

```bash
curl http://127.0.0.1:8000/api/health
```

返回 `{"status":"ok"}`。这个接口不检查 OCR、Ollama 或 DeepSeek。

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
| `sources` | 本次回答使用的内部片段和引用编号 |
| `delta` | 追加到页面的答案文本 |
| `replace` | 清空当前答案，接下来用增强答案替换 |
| `warning` | DeepSeek 未配置或远端失败等可降级问题 |
| `done` | 正常结束，包含 provider、scope 和来源数量 |
| `error` | 本地模型等关键步骤失败，无法继续回答 |

典型本地流程是 `stage(retrieving) → sources → stage(local_generating) → delta... → done`。DeepSeek 增强成功时会继续出现 `stage(deepseek_enhancing) → replace → delta... → done`。

`scope` 表示答案依据：`INTERNAL` 为较明确的内部资料，`INTERNAL_LIMITED` 为有限的语义证据，`GENERAL` 为无内部资料时的 DeepSeek 通用知识，`NONE` 为未找到内部答案。DeepSeek 未配置或调用失败时会发送 `warning`，并保留千问本地答案。

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

生产部署还应增加身份认证、权限隔离、速率限制和审计日志；当前本地版尚未实现这些能力。
