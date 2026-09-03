# Company Search

Mac 本地文档资料库。第一期提供安全上传、托管存储、重复检测、文件列表、下载和删除，为后续文档解析、OCR、切片和混合检索建立基础。

## 第一阶段能力

- 原文件复制到 `~/Library/Application Support/CompanySearch/`。
- 流式上传，单文件最大 200 MiB。
- SHA-256 内容去重，同名文件不会相互覆盖。
- 支持 PDF、DOCX、XLSX、PPTX、TXT、Markdown、CSV、PNG、JPG/JPEG。
- 浏览器中查看文件列表、上传进度、状态并下载或删除文件。
- 服务仅监听 `127.0.0.1`，不会开放到局域网或公网。

第一期只创建等待处理的任务，不执行解析、OCR、Embedding 或检索。这些能力将在后续阶段加入。

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
2. 通过 Homebrew 安装 `libmagic`。
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
GET    /api/documents/{id}/download
DELETE /api/documents/{id}
GET    /api/health
```

## 在 Mac 上验证

本批代码按照要求没有在服务器执行测试。拉取后请至少验证：

1. `./scripts/setup.sh` 能完成依赖安装和迁移。
2. `./scripts/start.sh` 能启动两个本地服务。
3. 九类文件均能上传。
4. 相同内容第二次上传会显示重复提示。
5. 下载文件与原文件一致。
6. 删除后文件列表和本地托管文件都消失。
7. 超过 200 MiB、空文件、伪造扩展名和旧版 Office 文件被拒绝。

如遇问题，请提供终端输出以及 `.run/backend.log` 或 `.run/frontend.log` 中相关部分。

## 设计文档

- [完整设计](docs/superpowers/specs/2026-09-03-local-document-search-design.md)
- [第一期实施计划](docs/superpowers/plans/2026-09-03-local-document-upload-phase1.md)
