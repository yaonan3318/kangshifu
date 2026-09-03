# Company Search

Mac 本地文档资料库。当前版本提供安全上传、托管存储、重复检测、文件管理、文档解析、本地 OCR 和结构化切片，为后续混合检索建立基础。

## 第一阶段能力

- 原文件复制到 `~/Library/Application Support/CompanySearch/`。
- 流式上传，单文件最大 200 MiB。
- SHA-256 内容去重，同名文件不会相互覆盖。
- 支持 PDF、DOCX、XLSX、PPTX、TXT、Markdown、CSV、PNG、JPG/JPEG。
- 浏览器中查看文件列表、上传进度、状态并下载或删除文件。
- 后台自动解析 PDF、DOCX、XLSX、PPTX、TXT、Markdown 和 CSV。
- 使用本机 Tesseract 对 PNG、JPG 和扫描型 PDF 执行中英文 OCR。
- 在文档详情中查看带页码、幻灯片、工作表和行号的文本片段。
- 服务仅监听 `127.0.0.1`，不会开放到局域网或公网。

当前版本处理到“已解析”状态，尚未执行 Embedding 和检索；这些能力将在第三期加入。

## Mac 环境要求

- macOS（目标机器：Apple M3 Pro，18 GB 内存）
- Python 3.12 或 3.13
- Node.js 20 或更高版本
- Docker Desktop
- Homebrew
- 至少 5 GB 可用磁盘

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

主要接口：

```text
POST   /api/documents/upload
GET    /api/documents
GET    /api/documents/{id}
GET    /api/documents/{id}/content
GET    /api/documents/{id}/download
POST   /api/documents/{id}/reprocess
DELETE /api/documents/{id}
GET    /api/health
```

## 第二期更新与验证

已有第一期环境时，拉取代码后必须再次运行安装脚本，以安装解析/OCR 依赖和执行新迁移：

```bash
git pull origin main
./scripts/stop.sh
./scripts/setup.sh
./scripts/start.sh
```

原有“等待处理”的文件会由 Worker 自动处理，无需重新上传。处理日志位于 `.run/worker.log`。

本批代码按照要求没有在服务器执行应用测试。请至少验证：

1. `./scripts/setup.sh` 能完成依赖安装和迁移。
2. `./scripts/start.sh` 能启动两个本地服务。
3. 九类文件均能上传。
4. 相同内容第二次上传会显示重复提示。
5. 下载文件与原文件一致。
6. 删除后文件列表和本地托管文件都消失。
7. TXT、Markdown、CSV、PDF、DOCX、XLSX 和 PPTX 能变成“已解析”。
8. PNG、JPG 和扫描 PDF 能通过 OCR 生成文本片段。
9. 点击“详情”可查看来源位置和内容，重新处理不会重复增加切片。

如遇问题，请提供终端输出以及 `.run/backend.log` 或 `.run/frontend.log` 中相关部分。

## 设计文档

- [完整设计](docs/superpowers/specs/2026-09-03-local-document-search-design.md)
- [第一期实施计划](docs/superpowers/plans/2026-09-03-local-document-upload-phase1.md)
