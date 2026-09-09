# P0 Mac 升级与验收

## 安全升级

新开终端后执行：

```bash
cd /Users/yaonan/kangpasi/kangshifu
git pull origin main
conda activate company-search
docker compose up -d db
cd backend
.venv/bin/alembic upgrade head
cd ..
./scripts/setup.sh
./scripts/start.sh
```

不要先运行 `stop.sh` 再单独执行 Alembic，因为停止脚本也会停止 PostgreSQL 容器。看到 `Running upgrade 0005_upload_batches -> 0006_knowledge_governance` 后刷新页面。

## 是否开启精排

默认 `.env` 为：

```env
COMPANY_SEARCH_RERANK_ENABLED=false
```

此时不会下载或加载 `bge-reranker-v2-m3`。先验收知识库、回收站和检索实验室；需要比较精排效果时再改成 `true`，重新运行 `setup.sh` 下载模型并重启。

## 验收清单

1. 原有资料仍在，并全部显示在“默认知识库”。
2. 创建第二个知识库，分别进行单文件上传和文件夹批量上传。
3. 停用知识库后，其资料不再出现在资料检索、知识问答和 Harness 结果中。
4. 停用单篇资料或单个片段，确认三个检索入口均不再召回。
5. 将资料移入回收站，确认原附件没有立即删除；恢复后可再次检索。
6. 在回收站输入完整文件名执行永久删除，确认无法恢复。
7. 编辑一个片段并保存，确认显示“人工修改”，搜索新文本可以命中。
8. 恢复片段原文，确认新文本不再命中；整篇重新处理人工片段时会二次提示。
9. 上传同一路径但内容不同的文件，等待新版本变为可检索，确认版本历史存在且旧版本停用。
10. 打开资料检索，确认显示实际模式、耗时、扩展词、可信度和降级提示。
11. 输入完全无关问题，确认页面显示没有可靠答案，千问不根据无关片段编造公司结论。
12. 在检索实验室查看关键词、向量、RRF、精排和最终上下文阶段。
13. 保存至少一个应有答案和一个应无答案用例，运行评测并查看 Recall@K、MRR、无答案准确率和耗时。

## 排错

数据库迁移状态：

```bash
cd backend
.venv/bin/alembic current
.venv/bin/alembic heads
```

服务日志：

```bash
tail -n 200 .run/backend.log
tail -n 200 .run/worker.log
tail -n 200 .run/frontend.log
```

如果页面显示“系统内部错误”，先确认数据库已经升级到 `0006_knowledge_governance`。如果精排提示降级，先关闭精排验证基础功能，再检查模型下载和可用内存。

## 本期有意延后

P0 不包含用户、部门和文档权限、SSO、用户评分影响排序、企业微信/钉钉/飞书、外部数据源同步、工作流、多智能体和 GraphRAG。
