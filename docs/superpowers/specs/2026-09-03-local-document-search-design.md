# Mac 本地文档检索系统设计

日期：2026-09-03

## 1. 目标

在 Apple M3 Pro、18 GB 内存的 MacBook Pro 上构建一个完全本地、单用户的文档管理与检索系统。系统负责托管原始文件、提取内容、执行 OCR、切片并建立关键词与向量索引，最终通过浏览器返回相关文档和带来源位置的原文片段。

第一版不提供生成式 LLM 回答和联网搜索。项目首先验证文档处理质量与前五条检索结果的召回率，并为后续 RAG、权限和服务器部署保留清晰的扩展边界。

## 2. 范围

### 2.1 包含

- 本机单用户，通过 `127.0.0.1` 访问，无登录功能。
- 上传、列表、筛选、查看信息、下载、删除及重复检测。
- 支持 PDF、DOCX、XLSX、PPTX、TXT、Markdown、CSV、PNG、JPG/JPEG。
- 图片和扫描型 PDF 使用本地 OCR。
- 展示等待、处理、成功、失败等状态，支持失败后重试。
- 文档结构化解析、内容清洗与切片。
- 本地中英文 Embedding。
- PostgreSQL 全文检索与 pgvector 向量检索，并用 RRF 合并排名。
- 查看解析文本、切片和来源位置。
- 本机安装、启动、停止和测试脚本。

### 2.2 不包含

- 生成式 LLM 回答、RAG 答案合成及联网搜索。
- 多用户、登录、部门权限和局域网访问。
- DOC、XLS、PPT 等旧版二进制 Office 格式。
- ZIP、音频、视频。
- Word、Excel、PPT 内嵌图片的 OCR。
- Kubernetes、Elasticsearch、Milvus、Redis、Celery 和对象存储。

## 3. 总体架构

```text
浏览器（Vue 3）
        |
FastAPI HTTP API
   |             |
PostgreSQL       Mac 本地托管文件目录
+ pgvector
   |
独立 Python Worker
   |
解析器 / OCR / 切片 / Embedding / 建索引
```

PostgreSQL 与 pgvector 使用 Docker 运行。FastAPI、Worker、OCR 和 Embedding 在 macOS 原生 Python 环境运行，以保留 Apple Silicon 的本地加速能力。Vue 开发服务器仅用于开发；发布版构建为静态资源并由应用提供。

Web 服务只监听 `127.0.0.1`，不向局域网或公网开放。

## 4. 本地数据目录

运行数据统一放置在：

```text
~/Library/Application Support/CompanySearch/
├── files/
│   ├── originals/
│   └── quarantine/
├── models/
├── temp/
├── logs/
└── backups/
```

原文件使用 UUID 作为内部文件名，并按年月分目录。原始文件名只存入数据库。数据库仅保存相对于资料库根目录的路径，保证数据可迁移。

## 5. 数据模型

### 5.1 documents

- `id`: UUID 主键。
- `original_name`: 用户上传时的文件名。
- `stored_path`: 托管文件的相对路径。
- `extension`: 标准化扩展名。
- `mime_type`: 根据文件内容检测的实际类型。
- `size_bytes`: 文件字节数。
- `sha256`: 内容摘要，建立唯一约束用于重复检测。
- `tags`: 用户维护的文档标签数组。
- `status`: 文档状态。
- `error_code`、`error_message`: 面向程序和用户的失败信息。
- `parser_name`、`parser_version`: 最近一次解析器信息。
- `embedding_model`、`embedding_version`: 当前向量版本。
- `created_at`、`updated_at`: 时间戳。

### 5.2 document_chunks

- `id`: 主键。
- `document_id`: 所属文档，级联删除。
- `sequence_number`: 文档内稳定顺序。
- `page_start`、`page_end`: PDF 页码；不适用时为空。
- `slide_number`: PPTX 幻灯片编号。
- `sheet_name`、`row_start`、`row_end`: 表格来源位置。
- `section_path`: 标题层级。
- `content`: 可检索原文。
- `ocr_confidence`: OCR 内容的平均置信度。
- `search_vector`: PostgreSQL 关键词索引。
- `embedding`: `vector(1024)`，与选定模型一致。
- `created_at`: 时间戳。

### 5.3 processing_jobs

- `id`: 主键。
- `document_id`: 所属文档。
- `job_type`: `parse`、`embed` 或 `reindex`。
- `status`: 等待、执行、成功或失败。
- `attempts`: 已尝试次数。
- `error_code`、`error_message`: 失败信息。
- `started_at`、`finished_at`: 执行时间。

同一文档同一任务类型在任意时刻只允许一个活动任务。

## 6. 上传事务

1. 浏览器以流式方式上传单个文件；页面可并行排队多个文件。
2. 后端将内容流式写入临时目录，同时计算 SHA-256，不把完整文件载入内存。
3. 校验 200 MB 上限、扩展名、MIME、文件头和允许类型。
4. 对可疑或类型不一致的内容拒绝处理或移入隔离目录。
5. 根据 SHA-256 查询重复内容。重复时删除临时文件并返回已有文档信息。
6. 为新文档生成 UUID，将临时文件原子移动到年月目录。
7. 在一个数据库事务内创建 `documents` 和 `processing_jobs`，文档状态置为 `PENDING`。
8. 数据库提交后返回文档 ID 与处理状态。
9. 数据库写入失败时清理已移动的孤立文件；后台处理失败时保留原文件并允许重试。

同名但内容不同的文件均可保存；内容完全相同的文件视为重复。第一版不直接覆盖旧记录。

## 7. 状态机与后台任务

文档正常状态：

```text
UPLOADING -> PENDING -> PARSING -> CHUNKING -> EMBEDDING -> INDEXING -> READY
```

失败状态包括 `UPLOAD_FAILED`、`PARSE_FAILED`、`OCR_FAILED` 和 `INDEX_FAILED`。损坏文件、加密文件和不支持的内容不自动重试；进程中断等临时错误进行有限重试。手动重新处理会创建新任务。

FastAPI 只接收文件和创建任务。独立 Worker 通过 PostgreSQL 行锁领取任务，默认单进程串行处理，避免多个 OCR 或 Embedding 任务占满内存。Worker 重启后重新领取超时的执行中任务。删除中的文档不再执行后续任务。

## 8. 文档解析

- PDF：PyMuPDF 提取文本块和页码。逐页判断是否有有效文字；无文字或疑似乱码的页面渲染后执行 OCR。
- DOCX：提取标题层级、段落和表格。图片第一版不做 OCR。
- XLSX：使用只读模式读取现有单元格值，不执行宏、公式计算和外部链接。保留工作表、表头及行号。
- PPTX：提取每页标题、文本框、表格和备注，保留幻灯片编号。图片第一版不做 OCR。
- TXT、Markdown：检测常见编码，保留自然段和 Markdown 标题层级。
- CSV：检测常见编码和分隔符，保留表头及行号。
- PNG、JPG/JPEG：修正方向、限制最大分辨率后执行本地 OCR，保存文本顺序与置信度。

解析器不执行宏、脚本或外部链接。每项任务设定时间与资源上限。临时文件在处理结束后清除，日志不记录完整正文。

## 9. 清洗与切片

PDF、DOCX 和 Markdown 优先按标题、段落和页面边界切分。目标为 400 至 800 个中文字符，最大约 1,200 个字符，相邻片段重叠约 80 至 120 个字符。标题路径加入片段上下文。

XLSX 和 CSV 使用“文件名 + 工作表 + 表头 + 若干完整数据行”组成片段，禁止将单个单元格脱离表头独立索引。PPTX 默认每张幻灯片一个结构单元，过长时再按段落拆分。OCR 内容按页面、版面区域和自然段重组并携带置信度。

切片算法必须按文件类型实现独立策略，并通过统一接口输出 `document_chunks`。

## 10. Embedding 与索引

第一版使用本地 `BAAI/bge-m3`，支持中文为主并包含英文术语的资料。模型保存在应用模型目录，首次安装时下载，之后可离线运行。模型标识与版本写入每个文档；模型变化时需要重新生成全部向量。

中文关键词在应用层分词，英文做小写化和基础规范化，结果写入 PostgreSQL `tsvector`。文件名、标题、标签和章节字段建立适合模糊匹配的索引。

文档只有在关键词和向量索引均完整后才进入 `READY`。失败或处理中记录不参与检索。

## 11. 混合检索

每次查询执行：

1. 规范化用户输入并生成中英文关键词。
2. 生成查询向量。
3. 分别取关键词检索前 30 条和 pgvector 语义检索前 30 条。
4. 使用 RRF 合并排名并按片段去重。
5. 返回前 10 条，并携带原文、文档信息和来源位置。

过滤条件包含文件类型、上传时间、文件名和状态，并在两路查询内部执行。结果标记来自关键词、语义或两者。第一版不将原始检索分数显示为百分比，也不引入 Reranker；验收数据表明排序不足时再增加重排模型。

## 12. 页面

### 12.1 文件管理

- 点击或拖拽上传，多文件分别显示进度。
- 按文件名、类型和状态筛选。
- 显示文件大小、时间、处理阶段和失败原因。
- 提供详情、下载、重试和删除操作。
- 删除前二次确认。

### 12.2 文档详情

- 展示元数据、SHA-256、解析器和模型版本。
- 分页查看解析正文及切片。
- 展示页码、工作表、行号或幻灯片等来源。
- 提供重新解析、重新索引和原文件下载。

### 12.3 检索

- 输入关键词或自然语言问题。
- 按类型和时间筛选。
- 展示文档名、章节、来源位置、命中片段、关键词高亮和匹配方式。
- OCR 结果显示识别提示。
- 提供查看详情和下载原文。

## 13. API

```text
POST   /api/documents/upload
GET    /api/documents
GET    /api/documents/{id}
GET    /api/documents/{id}/content
GET    /api/documents/{id}/download
POST   /api/documents/{id}/reprocess
DELETE /api/documents/{id}
POST   /api/search
GET    /api/jobs/{id}
GET    /api/health
```

API 使用稳定的错误代码与中文用户消息，禁止把 Python 堆栈返回给浏览器。

## 14. 删除一致性

删除请求先把文档置为 `DELETING`，阻止新任务和检索。随后在数据库事务中删除活动任务和片段，再尝试删除原文件；文件删除成功后才删除文档记录。文件删除失败时保留 `DELETING` 记录与错误信息，并由后续启动检查或维护任务重试，保证失败文件有明确归属且永远不再参与检索。

## 15. 启动与健康检查

提供：

```bash
./scripts/setup.sh
./scripts/start.sh
./scripts/stop.sh
```

启动时检查 PostgreSQL、pgvector、目录写权限、磁盘空间、本地模型和 Worker。健康接口分别报告 Web、数据库和 Worker 状态，不暴露敏感路径或文档内容。

## 16. 测试与验收

单元测试覆盖文件校验、SHA-256、状态转换、文本清洗、各类型切片和 RRF。解析测试使用固定样本覆盖九类文件、扫描 PDF、中文图片、损坏文件和加密文件。API 测试覆盖上传、重复检测、列表、下载、删除、重试和检索。

端到端验收准备至少 30 个中英文混合问题，并人工标注目标文件和位置。主要成功标准：

- 正确目标文档进入前五条结果。
- 返回片段包含所需信息且来源位置正确。
- 精确编号、中文同义表达和英文术语均可检索。
- 删除文档后立即不再出现在结果中。
- 非 `READY` 文档不参与检索。
- 应用重启后原始文件、索引和未完成任务保持一致。

## 17. 后续扩展边界

RAG 阶段在当前搜索服务之上增加答案生成模块，输入为检索片段，输出必须带文档引用。多用户阶段在文档和片段层增加访问策略，并要求两路检索都在查询内部执行权限过滤。服务器迁移阶段可将本地文件适配器替换为对象存储，并将原生 Worker 容器化，而不改变 API 和核心数据模型。
