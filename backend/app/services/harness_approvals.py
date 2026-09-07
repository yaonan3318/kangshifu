"""Harness 写操作审批、执行与状态校验。"""

from datetime import UTC, datetime, timedelta
import uuid

from sqlalchemy.orm import Session

from app.config import Settings
from app.harness.kubernetes import KubectlClient, KubectlError
from app.harness.types import PreparedOperation
from app.models import ApprovalStatus, HarnessApproval, HarnessStep, HarnessStepStatus, HarnessTask, HarnessTaskStatus


class ApprovalService:
    def __init__(self, session: Session, settings: Settings):
        self.session, self.settings, self.client = session, settings, KubectlClient(settings)

    def create(self, task: HarnessTask, step: HarnessStep, operation: PreparedOperation) -> HarnessApproval:
        approval = HarnessApproval(
            task_id=task.id, step_id=step.id, status=ApprovalStatus.PENDING,
            tool_name=operation.tool_name, context=task.context, namespace=task.namespace,
            target=operation.target, arguments=operation.arguments, yaml_content=operation.yaml_content,
            yaml_sha256=operation.yaml_sha256, dry_run_output=operation.dry_run_output,
            diff_output=operation.diff_output, resource_versions=operation.resource_versions,
            expires_at=datetime.now(UTC) + timedelta(minutes=self.settings.harness_approval_minutes),
        )
        step.status, task.status = HarnessStepStatus.AWAITING_APPROVAL, HarnessTaskStatus.AWAITING_APPROVAL
        self.session.add(approval); self.session.commit(); self.session.refresh(approval)
        return approval

    async def confirm(self, approval_id: uuid.UUID, confirmation_context: str) -> HarnessApproval:
        approval = self._pending(approval_id)
        if confirmation_context != approval.context:
            raise KubectlError("确认文字与目标 Kubernetes context 不一致")
        await self._verify_versions(approval)
        approval.status, approval.actor, approval.decided_at = ApprovalStatus.CONFIRMED, "local-user", datetime.now(UTC)
        self.session.commit()
        try:
            result = await self._execute(approval)
        except Exception as exc:
            approval.status = ApprovalStatus.FAILED
            approval.execution_result = {"success": False, "error": str(exc)}
            approval.task.status = HarnessTaskStatus.RUNNING
            step = self.session.get(HarnessStep, approval.step_id)
            if step: step.status = HarnessStepStatus.FAILED
            self.session.commit()
            return approval
        approval.status = ApprovalStatus.EXECUTED
        approval.execution_result = {"success": True, "output": result}
        approval.task.status = HarnessTaskStatus.RUNNING
        step = self.session.get(HarnessStep, approval.step_id)
        if step: step.status = HarnessStepStatus.SUCCEEDED
        self.session.commit(); self.session.refresh(approval)
        return approval

    def reject(self, approval_id: uuid.UUID, reason: str | None) -> HarnessApproval:
        approval = self._pending(approval_id)
        approval.status, approval.actor, approval.rejection_reason = ApprovalStatus.REJECTED, "local-user", reason
        approval.decided_at = datetime.now(UTC)
        approval.task.status = HarnessTaskStatus.RUNNING
        step = self.session.get(HarnessStep, approval.step_id)
        if step: step.status = HarnessStepStatus.REJECTED
        self.session.commit(); self.session.refresh(approval)
        return approval

    def _pending(self, approval_id: uuid.UUID) -> HarnessApproval:
        approval = self.session.get(HarnessApproval, approval_id)
        if not approval or approval.status != ApprovalStatus.PENDING:
            raise KubectlError("审批不存在或已处理")
        if approval.expires_at <= datetime.now(UTC):
            approval.status = ApprovalStatus.EXPIRED
            approval.task.status = HarnessTaskStatus.RUNNING
            self.session.commit()
            raise KubectlError("审批已经过期")
        return approval

    async def _verify_versions(self, approval: HarnessApproval) -> None:
        for target, expected in approval.resource_versions.items():
            kind, name = target.split("/", 1)
            current = await self.client.run(approval.context, ["-n", approval.namespace, "get", kind, name, "-o", "json"])
            actual = current.json().get("metadata", {}).get("resourceVersion", "")
            if actual != expected:
                approval.status = ApprovalStatus.EXPIRED; self.session.commit()
                raise KubectlError(f"{target} 已发生变化，需要重新生成审批")

    async def _execute(self, approval: HarnessApproval) -> str:
        a, c, n = approval.arguments, approval.context, approval.namespace
        timeout = self.settings.harness_write_timeout_seconds
        if approval.tool_name == "k8s_restart_deployment":
            args, stdin = ["-n", n, "rollout", "restart", f"deployment/{a['name']}"], None
        elif approval.tool_name == "k8s_scale_workload":
            args, stdin = ["-n", n, "scale", f"{a['kind']}/{a['name']}", f"--replicas={a['replicas']}"], None
        elif approval.tool_name == "k8s_rollback_deployment":
            args, stdin = ["-n", n, "rollout", "undo", f"deployment/{a['name']}"], None
        elif approval.tool_name == "k8s_update_image":
            args, stdin = ["-n", n, "set", "image", f"{a['kind']}/{a['name']}", f"{a['container']}={a['image']}"], None
        elif approval.tool_name == "k8s_apply_yaml":
            args, stdin = ["-n", n, "apply", "--server-side", "-f", "-"], approval.yaml_content
        else:
            raise KubectlError("审批工具不在写操作白名单中")
        result = await self.client.run(c, args, stdin, timeout)
        return result.stdout.strip() or "操作执行成功"

    def expire_and_cleanup(self) -> None:
        """过期未处理审批；审计清理采用级联删除超过保留期的任务。"""
        from sqlalchemy import delete, select
        now = datetime.now(UTC)
        for approval in self.session.scalars(select(HarnessApproval).where(HarnessApproval.status == ApprovalStatus.PENDING, HarnessApproval.expires_at <= now)):
            approval.status = ApprovalStatus.EXPIRED
            approval.task.status = HarnessTaskStatus.RUNNING
        cutoff = now - timedelta(days=self.settings.harness_audit_days)
        self.session.execute(delete(HarnessTask).where(HarnessTask.created_at < cutoff))
        self.session.commit()
