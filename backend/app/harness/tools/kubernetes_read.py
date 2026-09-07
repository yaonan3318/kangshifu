"""Kubernetes 只读工具及其参数定义。"""

from typing import Literal

from pydantic import BaseModel, Field

from app.harness.kubernetes import KubectlClient
from app.harness.types import ToolResult


class NamespaceArguments(BaseModel):
    context: str


class WorkloadArguments(BaseModel):
    context: str
    namespace: str = "default"
    selector: str | None = Field(default=None, max_length=300)


class ResourceArguments(BaseModel):
    context: str
    namespace: str = "default"
    kind: Literal["deployment", "statefulset", "daemonset", "pod", "service", "ingress", "job", "cronjob"]
    name: str


class PodLogsArguments(BaseModel):
    context: str
    namespace: str = "default"
    pod: str
    container: str | None = None
    tail: int = Field(default=200, ge=1, le=1000)


class EventsArguments(BaseModel):
    context: str
    namespace: str = "default"


def read_handlers(client: KubectlClient):
    async def namespaces(a: NamespaceArguments) -> ToolResult:
        result = await client.run(a.context, ["get", "namespaces", "-o", "json"])
        names = [item["metadata"]["name"] for item in result.json().get("items", [])]
        return ToolResult(summary=f"集群包含 {len(names)} 个 namespace", data=names, truncated=result.truncated)

    async def workloads(a: WorkloadArguments) -> ToolResult:
        client.validate_name(a.namespace, "namespace")
        args = ["-n", a.namespace, "get", "deployments,statefulsets,daemonsets,pods", "-o", "json"]
        if a.selector:
            args.extend(["-l", a.selector])
        result = await client.run(a.context, args)
        items = [{"kind": item.get("kind"), "name": item["metadata"]["name"], "status": item.get("status", {})} for item in result.json().get("items", [])]
        return ToolResult(summary=f"找到 {len(items)} 个工作负载或 Pod", data=items, truncated=result.truncated)

    async def describe(a: ResourceArguments) -> ToolResult:
        client.validate_name(a.namespace, "namespace"); client.validate_name(a.name)
        result = await client.run(a.context, ["-n", a.namespace, "describe", a.kind, a.name])
        return ToolResult(summary=f"已读取 {a.kind}/{a.name} 详情", data=result.stdout, truncated=result.truncated)

    async def logs(a: PodLogsArguments) -> ToolResult:
        client.validate_name(a.namespace, "namespace"); client.validate_name(a.pod, "Pod 名称")
        args = ["-n", a.namespace, "logs", a.pod, "--tail", str(a.tail)]
        if a.container:
            client.validate_name(a.container, "容器名称"); args.extend(["-c", a.container])
        result = await client.run(a.context, args)
        return ToolResult(summary=f"已读取 Pod {a.pod} 最近 {a.tail} 行日志", data=result.stdout, truncated=result.truncated)

    async def events(a: EventsArguments) -> ToolResult:
        client.validate_name(a.namespace, "namespace")
        result = await client.run(a.context, ["-n", a.namespace, "get", "events", "--sort-by=.lastTimestamp", "-o", "json"])
        items = result.json().get("items", [])[-100:]
        return ToolResult(summary=f"读取到 {len(items)} 条事件", data=items, truncated=result.truncated)

    async def rollout(a: ResourceArguments) -> ToolResult:
        if a.kind not in {"deployment", "statefulset", "daemonset"}:
            raise ValueError("该资源不支持 rollout status")
        result = await client.run(a.context, ["-n", a.namespace, "rollout", "status", f"{a.kind}/{a.name}", "--timeout=20s"])
        return ToolResult(summary=result.stdout.strip() or "rollout 状态查询完成", data=result.stdout)

    async def resource_yaml(a: ResourceArguments) -> ToolResult:
        result = await client.run(a.context, ["-n", a.namespace, "get", a.kind, a.name, "-o", "yaml"])
        return ToolResult(summary=f"已读取 {a.kind}/{a.name} YAML", data=result.stdout, truncated=result.truncated)

    return namespaces, workloads, describe, logs, events, rollout, resource_yaml
