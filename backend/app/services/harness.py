"""持久化 Agent Harness 主循环。"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.harness import HarnessPlanner
from app.harness.kubernetes import KubectlError
from app.harness.tools import build_tool_registry
from app.harness.types import PreparedOperation, ToolResult
from app.llm import DeepSeekClient, GenerationMessage, LlmError, OllamaClient
from app.models import ApprovalStatus, HarnessApproval, HarnessStep, HarnessStepStatus, HarnessTask, HarnessTaskStatus
from app.schemas.answer import AnswerEvent, AnswerProvider, AnswerRequest, KnowledgeScope
from app.services.audit import record as audit_record
from app.services.harness_approvals import ApprovalService


class HarnessService:
    def __init__(self, session: Session, settings: Settings, user=None):
        self.session, self.settings, self.user = session, settings, user
        self.registry = build_tool_registry(session, settings)
        self.planner = HarnessPlanner(OllamaClient(settings))
        self.deepseek = DeepSeekClient(settings)

    async def start(self, request: AnswerRequest) -> AsyncIterator[AnswerEvent]:
        context = (request.k8s_context or "").strip()
        if context not in self.settings.allowed_k8s_contexts:
            yield AnswerEvent(type="error", error={"code": "K8S_CONTEXT_NOT_ALLOWED", "message": "请选择配置白名单中的 Kubernetes context"}); return
        namespace = (request.k8s_namespace or "default").strip()
        task = HarnessTask(
            question=request.question.strip(), context=context, namespace=namespace,
            status=HarnessTaskStatus.RUNNING, model=self.settings.ollama_model,
            max_steps=self.settings.harness_max_steps,
            history=[{"conversation": [turn.model_dump() for turn in request.history[-self.settings.rag_history_turns:]]}],
            deployment_yaml=request.deployment_yaml,
            deadline_at=datetime.now(UTC) + timedelta(seconds=self.settings.harness_timeout_seconds),
        )
        self.session.add(task); self.session.commit(); self.session.refresh(task)
        yield AnswerEvent(type="harness_started", task_id=task.id, tool_result={"context": context, "namespace": namespace, "max_steps": task.max_steps})
        async for event in self._run(task, request.use_deepseek):
            yield event

    async def resume(self, task_id: uuid.UUID, use_deepseek: bool = False) -> AsyncIterator[AnswerEvent]:
        task = self.get_task(task_id)
        if task.status == HarnessTaskStatus.AWAITING_APPROVAL:
            yield AnswerEvent(type="error", task_id=task.id, error={"code": "APPROVAL_REQUIRED", "message": "请先确认或拒绝待处理操作"}); return
        latest = self.session.scalar(select(HarnessApproval).where(HarnessApproval.task_id == task.id).order_by(HarnessApproval.created_at.desc()).limit(1))
        if latest and latest.status in {ApprovalStatus.EXECUTED, ApprovalStatus.REJECTED, ApprovalStatus.FAILED, ApprovalStatus.EXPIRED}:
            task.history = [*task.history, {"tool": latest.tool_name, "result": latest.execution_result or {"status": latest.status.value, "reason": latest.rejection_reason}}]
            self.session.commit()
        async for event in self._run(task, use_deepseek):
            yield event

    def get_task(self, task_id: uuid.UUID) -> HarnessTask:
        task = self.session.scalar(select(HarnessTask).where(HarnessTask.id == task_id).options(selectinload(HarnessTask.steps), selectinload(HarnessTask.approvals)))
        if not task:
            raise KubectlError("Harness 任务不存在")
        return task

    async def _run(self, task: HarnessTask, use_deepseek: bool) -> AsyncIterator[AnswerEvent]:
        while task.current_step < task.max_steps and datetime.now(UTC) < task.deadline_at:
            try:
                # 初始 history 可能包含上一轮对话，但它不能替代本次任务的工具证据。
                # 本次 Harness 尚未调用工具时，强制规划器先执行一个白名单工具。
                has_tool_evidence = any(item.get("tool") for item in task.history)
                decision = await self.planner.decide(
                    task.question,
                    task.context,
                    task.namespace,
                    self.registry,
                    task.history,
                    bool(task.deployment_yaml),
                    require_tool=not has_tool_evidence,
                )
            except LlmError as exc:
                task.status, task.error_code, task.error_message = HarnessTaskStatus.FAILED, exc.code, exc.message
                self.session.commit()
                yield AnswerEvent(type="error", task_id=task.id, error={"code": exc.code, "message": exc.message})
                return
            task.current_step += 1
            if decision.action == "final_answer":
                answer = decision.answer or ""
                yield AnswerEvent(type="delta", task_id=task.id, provider=AnswerProvider.LOCAL, text=answer)
                final_provider = AnswerProvider.LOCAL
                if use_deepseek and not self.deepseek.configured:
                    yield AnswerEvent(type="warning", warning={"code": "DEEPSEEK_NOT_CONFIGURED", "message": "尚未配置 DeepSeek API Key，本次使用本地模型回答。"})
                if use_deepseek and self.deepseek.configured:
                    parts = []
                    try:
                        async for delta in self.deepseek.stream([GenerationMessage(role="system", content="只增强下面的最终分析，不得提出或调用工具，不得虚构执行结果。"), GenerationMessage(role="user", content=answer)]): parts.append(delta)
                    except LlmError as exc:
                        yield AnswerEvent(type="warning", warning={"code": exc.code, "message": exc.message})
                    else:
                        if parts:
                            answer = "".join(parts); final_provider = AnswerProvider.DEEPSEEK
                            yield AnswerEvent(type="replace", provider=final_provider, text=""); yield AnswerEvent(type="delta", provider=final_provider, text=answer)
                task.final_answer, task.status, task.completed_at = answer, HarnessTaskStatus.COMPLETED, datetime.now(UTC)
                self.session.commit()
                yield AnswerEvent(type="harness_done", task_id=task.id, provider=final_provider, scope=KnowledgeScope.INTERNAL, step=task.current_step)
                return
            tool = self.registry.get(decision.tool or "")
            arguments = dict(decision.arguments)
            fields = tool.arguments_model.model_fields
            if "context" in fields: arguments["context"] = task.context
            if "namespace" in fields: arguments["namespace"] = task.namespace
            if tool.name == "k8s_apply_yaml" and task.deployment_yaml:
                # 原始 YAML 由用户直接提交；绝不采用模型复述或修改后的 YAML。
                arguments["yaml_content"] = task.deployment_yaml
            validated = self.registry.validate(tool.name, arguments)
            step = HarnessStep(task_id=task.id, sequence_number=task.current_step, status=HarnessStepStatus.RUNNING, tool_name=tool.name, reason=decision.reason, arguments=validated.model_dump())
            self.session.add(step); self.session.commit(); self.session.refresh(step)
            audit_record(
                self.session, "harness_tool_requested", user=self.user,
                target_type="harness_task", target_id=task.id,
                detail={"tool": tool.name, "arguments": validated.model_dump()},
            )
            yield AnswerEvent(type="tool_requested", task_id=task.id, step=task.current_step, tool=tool.name, tool_arguments=validated.model_dump(), tool_result={"reason": decision.reason})
            yield AnswerEvent(type="tool_running", task_id=task.id, step=task.current_step, tool=tool.name)
            started = time.monotonic()
            try:
                result = await tool.handler(validated)
            except Exception as exc:
                step.status, step.error_code, step.error_message = HarnessStepStatus.FAILED, "TOOL_FAILED", str(exc)
                task.history = [*task.history, {"tool": tool.name, "error": str(exc)}]
                result_payload = {"success": False, "error": str(exc)}
                audit_record(
                    None, "harness_tool_failed", user=self.user,
                    target_type="harness_task", target_id=task.id,
                    detail={"tool": tool.name, "error_code": "TOOL_FAILED"},
                    success=False, error_code="TOOL_FAILED",
                )
            else:
                if isinstance(result, PreparedOperation):
                    approval = ApprovalService(self.session, self.settings).create(task, step, result)
                    yield AnswerEvent(type="approval_required", task_id=task.id, step=task.current_step, tool=tool.name, approval=self._approval_payload(approval))
                    return
                step.status, step.result = HarnessStepStatus.SUCCEEDED, result.model_dump()
                task.history = [*task.history, {"tool": tool.name, "result": result.model_dump()}]
                result_payload = result.model_dump()
            step.duration_ms, step.finished_at = int((time.monotonic() - started) * 1000), datetime.now(UTC)
            self.session.commit()
            yield AnswerEvent(type="tool_result", task_id=task.id, step=task.current_step, tool=tool.name, tool_result=result_payload)
        task.status, task.error_code, task.error_message = HarnessTaskStatus.FAILED, "HARNESS_LIMIT_REACHED", "Harness 已达到步骤或时间上限"
        self.session.commit()
        yield AnswerEvent(type="error", task_id=task.id, error={"code": task.error_code, "message": task.error_message})

    @staticmethod
    def _approval_payload(value: HarnessApproval) -> dict:
        return {"id": str(value.id), "tool_name": value.tool_name, "context": value.context, "namespace": value.namespace, "target": value.target, "arguments": value.arguments, "yaml_content": value.yaml_content, "dry_run_output": value.dry_run_output, "diff_output": value.diff_output, "expires_at": value.expires_at.isoformat()}
