# Mac 批量导入验证

## 更新与迁移

```bash
cd /Users/yaonan/kangpasi/kangshifu
conda activate company-search
git pull origin main
./scripts/stop.sh
./scripts/setup.sh
./scripts/start.sh
```

运行 `select version_num from alembic_version;` 应看到 `0005_upload_batches`。

## 页面验证

1. 打开 `http://127.0.0.1:5173` 并进入“资料库”。
2. 选择“批量导入”，填写名称后选择多个文件或整个文件夹。
3. 在“导入批次”查看可检索、处理中、重复和失败数量。
4. 上传过程中关闭页面；重新进入批次，点击“继续上传”并选择原文件夹。
5. 验证已完成文件跳过，只上传待处理或失败文件。
6. 上传两份内容相同但文件名不同的文件，第二份应显示 `DUPLICATE`。
7. 对失败项执行“重试”或“忽略”，其他文件不受影响。

日志：

```bash
tail -n 200 .run/backend.log
tail -n 200 .run/worker.log
```

最后回归单文件上传、下载、资料检索、知识问答和 Harness。
