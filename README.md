# Company Search

Mac 本地公司知识库。当前版本提供安全上传、文档解析、本地 OCR、混合检索，以及由千问和可选 DeepSeek 驱动的 RAG 问答。

## 第一阶段能力

- 原文件复制到 `~/Library/Application Support/CompanySearch/`。
- 流式上传，单文件最大 200 MiB。
- SHA-256 内容去重，同名文件不会相互覆盖。
- 支持 PDF、DOCX、XLSX、PPTX、TXT、Markdown、CSV、PNG、JPG/JPEG。
- 浏览器中查看文件列表、上传进度、状态并下载或删除文件。
- 后台自动解析 PDF、DOCX、XLSX、PPTX、TXT、Markdown 和 CSV。
- 使用本机 Tesseract 对 PNG、JPG 和扫描型 PDF 执行中英文 OCR。
- 在文档详情中查看带页码、幻灯片、工作表和行号的文本片段。
- 使用本地 `BAAI/bge-m3` 生成 1024 维语义向量，模型和资料均不发送到外部服务。
- 使用 PostgreSQL 全文索引和 pgvector 分别召回候选片段，并通过 RRF 融合排序。
- 语义候选必须达到最低相似度，结果不会为了凑满数量而返回明显无关的文档。
- 可按文件类型、文件名和添加日期筛选，结果显示来源位置、OCR 信息及命中方式。
- 默认使用 Ollama `qwen3:8b` 在本机根据检索片段生成带引用的答案。
- 用户主动打开开关后，可让 DeepSeek 根据内部片段和千问初稿生成合并答案。
- DeepSeek 未配置或调用失败时保留本地答案，不会中断问答。
- 服务仅监听 `127.0.0.1`，不会开放到局域网或公网。
- 可选开启本地 Agent Harness，让千问调用公司检索和 Kubernetes 白名单工具；所有写操作逐次人工确认。
- 支持多个知识库、文档标签、版本关系、停用和永久保留的回收站。
- 支持人工编辑、停用、恢复和重新索引单个文档片段。
- 提供检索实验室，展示关键词、语义、RRF、精排和最终上下文，并保存标准问题评测结果。
- 可选使用本地 `BAAI/bge-reranker-v2-m3` 精排；关闭时不下载、不加载、不占运行内存。
- 功能级 RBAC（12 个固定权限码 + 四个默认角色）与文档 ACL 双层权限；前端按权限展示菜单，后端逐接口校验。
- P2-0 质量基线：评测集管理（含 CSV/Excel 导入）、检索配置版本化，以及新旧版本在同一评测集上的指标对比。
- P2-1 检索准确性：Query Rewrite 与多轮上下文补全、Multi-query 多查询召回、Reranker 精排（含重排前后名次）、元数据/结构化过滤、管理员维护的中文检索词典与拼写纠正。
- P2-2 回答可靠性：答案置信度分级（高/中/资料不足）、无答案与低置信度归因处理、引用真实性校验与“推断”标记、可追溯引用（版本/命中关键词/下载）、按问题类型的答案结构模板。
- P2-3 助手角色增强：助手可配置答案模板/联网/无答案策略/能力说明，预置六个角色助手；用户端只展示可理解的信息（当前助手、知识库、是否允许通用知识与运维），并提供助手欢迎页。
- P2-4 轻量 Chatflow：固定画布配置问答节点与条件分支，支持节点启停、失败/超时、调试运行与逐节点耗时、草稿/发布/回滚版本，不同助手可绑定不同流程。
- P2-5 用户体验与展示：回答过程可视化与流式优化、推荐追问、答案操作（复制/重新生成/导出 MD·PDF/反馈/举报）、知识缺口中心（指派/关联文档/重跑对比）、首页数据看板。
- P2-6 文档理解能力：PDF 标题层级/页眉页脚/多栏/表格/图注/OCR 与 Office 解析增强；按知识库配置切片策略并预览；文档作者/部门/主题/关联文档等图谱基础数据。

## Mac 环境要求

- macOS（目标机器：Apple M3 Pro，18 GB 内存）
- Python 3.12 或 3.13
- Node.js 20 或更高版本
- Docker Desktop
- Homebrew
- Ollama 和本地 `qwen3:8b`（仅知识问答需要）
- 至少 10 GB 可用磁盘

## 安装

克隆仓库后进入项目目录：

```bash
git clone git@github.com:yaonan3318/kangshifu.git
cd kangshifu
./scripts/setup.sh
```

安装脚本会：

1. 检查 macOS、Python、Node、Docker 和磁盘空间。
2. 通过 Homebrew 安装 `libmagic`、`tesseract` 和中文语言包。
3. 创建 `backend/.venv` 并安装后端依赖。
4. 安装前端依赖。
5. 启动 PostgreSQL + pgvector。
6. 执行 Alembic 数据库迁移。
7. 下载 BGE-M3 到本机资料目录。首次下载耗时取决于网络，后续安装会复用缓存。
8. 如果 `.env` 开启 `COMPANY_SEARCH_RERANK_ENABLED=true`，同时准备本地精排模型。

`setup.sh` 不会自动安装 Ollama、登录云端账号或修改其他项目的 Conda 环境。安装 Ollama 后执行：

```bash
ollama pull qwen3:8b
./scripts/check-llm.sh
```

## 启动与停止

```bash
./scripts/start.sh
```

浏览器访问：

```text
http://127.0.0.1:5173
```

停止服务：

```bash
./scripts/stop.sh
```

运行日志位于项目的 `.run/` 目录。上传的原文件和未来的模型不存入 Git。

## 数据位置与备份

默认资料目录：

```text
~/Library/Application Support/CompanySearch/
```

其中包括原始文件、临时目录、日志、模型和备份目录。PostgreSQL 数据保存在 Docker volume `company_search_postgres` 中。

备份时需要同时备份资料目录和 PostgreSQL 数据；只备份其中一个不能保证数据一致。运行 `docker compose down -v` 会删除数据库 volume，请勿把它当作普通停止命令。

## API

后端运行后可访问：

```text
http://127.0.0.1:8000/docs
```

同时提供 ReDoc（`http://127.0.0.1:8000/redoc`）和 OpenAPI JSON（`http://127.0.0.1:8000/openapi.json`）。请求参数、响应结构、SSE 事件、curl 示例及 Nginx 注意事项见 [后端接口手册](docs/backend-api.md)。

主要接口：

```text
POST   /api/documents/upload
GET    /api/documents
GET    /api/documents/{id}
GET    /api/documents/{id}/content
GET    /api/documents/{id}/download
POST   /api/documents/{id}/reprocess
DELETE /api/documents/{id}
GET    /api/knowledge-bases
GET    /api/documents?deleted=true
POST   /api/documents/{id}/restore
DELETE /api/documents/{id}/purge
GET    /api/documents/{id}/chunks
PATCH  /api/chunks/{id}
POST   /api/search
POST   /api/retrieval-lab/inspect
GET    /api/retrieval-lab/cases
POST   /api/retrieval-lab/runs
GET    /api/answer/status
POST   /api/answer/stream
GET    /api/health
```

认证与功能权限接口：

```text
GET    /api/auth/me            # 返回当前用户角色与有效权限码
GET    /api/auth/permissions   # 仅返回当前用户有效权限码（刷新菜单用）
GET    /api/roles/permissions  # 功能权限码目录（需 IDENTITY_MANAGE）
```

系统管理接口（需 `IDENTITY_MANAGE`，超级管理员自动通过）：

```text
GET    /api/users
POST   /api/users
GET    /api/users/{id}
PATCH  /api/users/{id}
POST   /api/users/{id}/enable
POST   /api/users/{id}/disable
POST   /api/users/{id}/reset-password
GET    /api/departments/tree
POST   /api/departments
PATCH  /api/departments/{id}
POST   /api/departments/{id}/enable
POST   /api/departments/{id}/disable
GET    /api/roles
POST   /api/roles
PATCH  /api/roles/{id}
POST   /api/roles/{id}/enable
POST   /api/roles/{id}/disable
PUT    /api/roles/{id}/users
GET    /api/roles/{id}/documents
GET    /api/audit/logs
GET    /api/documents/{id}/acl
PUT    /api/documents/{id}/access
PATCH  /api/documents/{id}/external-policy
```

## 功能权限（RBAC）

- 迁移 `0018_function_rbac` 新增 `permissions` / `role_permissions`，并幂等创建四个默认角色：
  普通员工、资料维护员、知识库管理员、系统管理员。
- 固定权限码：`ANSWER_USE`、`SEARCH_USE`、`DOCUMENT_VIEW`、`DOCUMENT_UPLOAD`、
  `DOCUMENT_MANAGE`、`KNOWLEDGE_BASE_MANAGE`、`RETRIEVAL_LAB_USE`、`ASSISTANT_MANAGE`、
  `IDENTITY_MANAGE`、`AUDIT_VIEW`、`STATS_VIEW`、`HARNESS_USE`。
- 用户有效权限为所有启用角色权限的并集；超级管理员拥有全部权限；`HARNESS_USE` 仅超级管理员有效。
- 功能权限不替代文档 ACL：查看/管理资料仍需通过文档级 READ / MANAGE 校验。
- 无权限返回 403 `PERMISSION_DENIED`，未登录返回 401 `AUTH_REQUIRED`；拒绝事件写入审计。
- 完整权限码与接口映射、默认角色和 Mac 验收手册见 [P1 升级说明](docs/p1-upgrade-guide.md)。

## P2-0 质量基线

- “检索实验室”提供评测集管理：创建评测集、添加标准问题（正确/必须引用/禁止召回文档、答案关键点、是否应无答案），支持 CSV/Excel 批量导入与批量运行。
- 评测指标：正确文档/片段召回率、Top1/Top3/Top5 命中率、答案关键点覆盖率、引用正确率、无答案判断正确率、首字与完整回答耗时、禁止召回违规数。
- 检索配置版本化：关键词/向量召回数量、RRF 常数与权重、Reranker 开关与模型、精排候选、相似度阈值、最终片段数量、Query Rewrite 同义词均可保存为版本。
- 同一评测集上可对比两次运行，输出指标变化、配置差异与逐用例变化。详见 [P1 升级说明](docs/p1-upgrade-guide.md#p2-0-质量基线评测集--检索配置版本)。

## 第四期 RAG 问答配置

本地问答不需要任何云端账号。千问通过独立的 Ollama 进程运行，回答完成后立即释放模型运行内存，模型文件继续保留在硬盘。

如需 DeepSeek 增强，只把 API Key 写入 Mac 本地的 `backend/.env`：

```env
COMPANY_SEARCH_DEEPSEEK_API_KEY=替换为你的真实Key
```

不要把真实 Key 写入 `.env.example`、Python、Vue、截图或 Git。修改配置后需要重启：

```bash
./scripts/stop.sh
./scripts/start.sh
```

DeepSeek 开关默认关闭。打开开关但没有填写 Key 时，系统仍返回千问本地答案，并提示“尚未配置 DeepSeek API Key，本次使用本地模型回答”。打开且配置有效时，本次问题、引用片段和千问初稿会发送给 DeepSeek。

## P0 知识治理与精排

升级后系统会自动创建“默认知识库”，历史资料、OCR、切片和向量不会丢失。普通删除只会把资料移入回收站；回收站内容立即停止参与资料检索、知识问答和 Harness，只有明确执行“永久删除”才会移除原附件。

默认继续使用原有混合检索，不额外占用精排模型内存。如需在 M3 Pro 上验证本地精排：

```env
COMPANY_SEARCH_RERANK_ENABLED=true
```

保存到 `backend/.env` 后执行：

```bash
./scripts/stop.sh
./scripts/setup.sh
./scripts/start.sh
```

模型下载或推理失败时，单次请求会自动降级为 RRF，页面显示提示，上传、检索和问答仍可继续。

## 可选 Harness 配置

Harness 默认关闭且不会自动读取本机所有 Kubernetes 集群。先确认 `kubectl config get-contexts` 中的名称，再只把允许操作的 context 写入 `backend/.env`：

```env
COMPANY_SEARCH_K8S_ALLOWED_CONTEXTS=docker-desktop,dev-cluster
```

重启应用后，知识问答页会显示 Harness 开关以及 context/namespace 选择器。关闭时保持原来的固定 RAG；打开后千问可以调用资料检索、Pod、日志、事件等只读工具。重启、扩缩容、回滚、镜像更新和 YAML apply 每次都要求输入完整 context 名称确认。首次验证请使用测试集群，详细步骤见 [Harness Mac 验收手册](docs/harness-mac-verification.md)。

### Mac 验证顺序

更新代码后运行：

```bash
conda activate company-search
./scripts/stop.sh
./scripts/setup.sh
./scripts/check-llm.sh
./scripts/start.sh
```

依次验证：

1. 关闭 DeepSeek，提出文档内问题，回答显示“千问本地回答”并带真实来源。
2. 打开 DeepSeek但不配置 Key，仍得到本地答案并看到未配置提示。
3. 配置 Key并重启，打开开关后得到“DeepSeek 增强”答案。
4. 临时退出 Ollama，页面显示本地模型未就绪及修复命令。
5. 提出资料库完全没有的问题：关闭开关时只提示内部资料没有答案；打开 DeepSeek 时显示明确标记的通用知识。
6. 连续追问一次，确认每轮都有新的检索阶段；刷新页面后历史清空。
7. 回答结束后执行 `ollama ps`，确认 `qwen3:8b` 不持续占用运行内存。
8. DeepSeek 不可用或余额不足时，确认千问本地答案仍然保留。

## 第三期更新与验证

已有第一期环境时，拉取代码后必须再次运行安装脚本，以安装解析/OCR 依赖和执行新迁移：

```bash
git pull origin main
./scripts/stop.sh
./scripts/setup.sh
./scripts/start.sh
```

原有“已解析”的文件会由数据库迁移自动加入索引队列，无需重新上传。向量化期间状态依次显示“向量化中”“建立索引”，完成后显示“可检索”。处理日志位于 `.run/worker.log`。

本批代码按照要求没有在服务器执行应用测试。请至少验证：

1. `./scripts/setup.sh` 能完成依赖安装和迁移。
2. `./scripts/start.sh` 能启动两个本地服务。
3. 九类文件均能上传。
4. 相同内容第二次上传会显示重复提示。
5. 下载文件与原文件一致。
6. 删除后文件列表和本地托管文件都消失。
7. TXT、Markdown、CSV、PDF、DOCX、XLSX 和 PPTX 最终能变成“可检索”。
8. PNG、JPG 和扫描 PDF 能通过 OCR 生成文本片段。
9. 点击“详情”可查看来源位置和内容，重新处理不会重复增加切片。
10. 用文档原词能够命中“关键词”或“混合命中”结果。
11. 用含义相近但措辞不同的问题能够得到“语义”或“混合命中”结果。
12. 文件类型、文件名和日期筛选能正确缩小两路检索结果。

如遇问题，请提供终端输出以及 `.run/backend.log` 或 `.run/frontend.log` 中相关部分。

## 设计文档

- [完整设计](docs/superpowers/specs/2026-09-03-local-document-search-design.md)
- [第一期实施计划](docs/superpowers/plans/2026-09-03-local-document-upload-phase1.md)
- [第二期实施计划](docs/superpowers/plans/2026-09-03-local-document-processing-phase2.md)
- [第三期实施计划](docs/superpowers/plans/2026-09-03-local-hybrid-search-phase3.md)
- [第四期设计](docs/superpowers/specs/2026-09-03-local-rag-answering-design.md)
- [第四期实施计划](docs/superpowers/plans/2026-09-03-local-rag-answering-phase4.md)
- [P0 产品设计](docs/superpowers/specs/2026-09-09-company-knowledge-assistant-p0-design.md)
- [P0 实施计划](docs/superpowers/plans/2026-09-09-company-knowledge-assistant-p0.md)
