# Harness Mac 本地验收

## 准备隔离环境

首次不要使用生产集群。执行 `kubectl config get-contexts` 确认本地 context，然后在 `backend/.env` 添加测试 context：

```env
COMPANY_SEARCH_K8S_ALLOWED_CONTEXTS=docker-desktop
```

更新依赖、迁移数据库并重启：

```bash
./scripts/setup.sh
./scripts/stop.sh
./scripts/start.sh
```

## 页面验证

1. Harness 关闭，提问公司资料问题，确认行为与原版本一致。
2. 打开 Harness，确认显示配置的 context 和 namespace。
3. 提问“查询 default namespace 的 Pod 状态”，确认显示工具申请、运行和结果。
4. 提问“读取某个 Pod 最近 50 行日志”，确认日志默认折叠。
5. 提问“重启某 Deployment”，确认只出现审批卡片，未确认前资源不变。
6. 输入错误 context 时确认按钮不可用；输入完整 context 后才能执行。
7. 点击拒绝，确认千问能够说明操作被拒绝。

## YAML 和失败验证

使用专用测试 namespace 和无敏感数据的 ConfigMap/Deployment。确认页面先显示 server-side dry-run 与 diff。Secret、Namespace、RBAC、CRD、PV、超过 20 个资源或大于 1 MiB 的 YAML 必须被拒绝。

还应验证不存在的 context、无写权限 kubeconfig、10 分钟审批过期，以及审批期间资源变化。使用数据库工具检查 `harness_tasks`、`harness_steps`、`harness_approvals` 已记录调用、决定和结果。

Harness 调试日志位于 `.run/backend.log`。不要把真实 API Key、kubeconfig、Secret 或生产 YAML 提交到 Git。
