"""Kubernetes 写工具：这里只准备和预检操作，不直接执行。"""

import hashlib
import json
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from app.harness.kubernetes import KubectlClient, KubectlError
from app.harness.types import PreparedOperation

ALLOWED_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Service", "Ingress", "ConfigMap", "Job", "CronJob", "HorizontalPodAutoscaler"}


class RestartArguments(BaseModel):
    context: str; namespace: str = "default"; name: str


class ScaleArguments(BaseModel):
    context: str; namespace: str = "default"
    kind: Literal["deployment", "statefulset"] = "deployment"
    name: str; replicas: int = Field(ge=0, le=100)


class RollbackArguments(BaseModel):
    context: str; namespace: str = "default"; name: str


class UpdateImageArguments(BaseModel):
    context: str; namespace: str = "default"
    kind: Literal["deployment", "statefulset", "daemonset"] = "deployment"
    name: str; container: str; image: str = Field(min_length=1, max_length=500)


class ApplyYamlArguments(BaseModel):
    context: str; namespace: str = "default"
    yaml_content: str = Field(min_length=1, max_length=1_048_576)


async def _version(client: KubectlClient, context: str, namespace: str, kind: str, name: str) -> dict[str, str]:
    result = await client.run(context, ["-n", namespace, "get", kind, name, "-o", "json"], accepted_codes={0, 1})
    if result.returncode:
        return {}
    value = result.json()
    return {f"{kind}/{name}": value.get("metadata", {}).get("resourceVersion", "")}


def write_handlers(client: KubectlClient):
    async def restart(a: RestartArguments) -> PreparedOperation:
        client.validate_name(a.namespace, "namespace"); client.validate_name(a.name)
        versions = await _version(client, a.context, a.namespace, "deployment", a.name)
        return PreparedOperation(tool_name="k8s_restart_deployment", target=f"deployment/{a.name}", arguments=a.model_dump(), dry_run_output="将触发 Deployment 滚动重启", resource_versions=versions)

    async def scale(a: ScaleArguments) -> PreparedOperation:
        client.validate_name(a.namespace, "namespace"); client.validate_name(a.name)
        versions = await _version(client, a.context, a.namespace, a.kind, a.name)
        return PreparedOperation(tool_name="k8s_scale_workload", target=f"{a.kind}/{a.name}", arguments=a.model_dump(), dry_run_output=f"副本数将变更为 {a.replicas}", resource_versions=versions)

    async def rollback(a: RollbackArguments) -> PreparedOperation:
        client.validate_name(a.namespace, "namespace"); client.validate_name(a.name)
        versions = await _version(client, a.context, a.namespace, "deployment", a.name)
        return PreparedOperation(tool_name="k8s_rollback_deployment", target=f"deployment/{a.name}", arguments=a.model_dump(), dry_run_output="将回滚到上一 Deployment revision", resource_versions=versions)

    async def image(a: UpdateImageArguments) -> PreparedOperation:
        client.validate_name(a.namespace, "namespace"); client.validate_name(a.name); client.validate_name(a.container, "容器名称")
        if a.image.startswith("-") or any(char.isspace() for char in a.image):
            raise KubectlError("镜像名称格式无效")
        versions = await _version(client, a.context, a.namespace, a.kind, a.name)
        preview = await client.run(a.context, ["-n", a.namespace, "set", "image", f"{a.kind}/{a.name}", f"{a.container}={a.image}", "--dry-run=server", "-o", "yaml"])
        return PreparedOperation(tool_name="k8s_update_image", target=f"{a.kind}/{a.name}", arguments=a.model_dump(), dry_run_output=preview.stdout, resource_versions=versions)

    async def apply_yaml(a: ApplyYamlArguments) -> PreparedOperation:
        documents = [item for item in yaml.safe_load_all(a.yaml_content) if item]
        if not documents or len(documents) > 20:
            raise KubectlError("YAML 必须包含 1 到 20 个资源")
        targets, versions = [], {}
        for item in documents:
            if not isinstance(item, dict) or item.get("kind") not in ALLOWED_KINDS:
                raise KubectlError(f"不允许部署资源类型：{item.get('kind') if isinstance(item, dict) else 'invalid'}")
            metadata = item.get("metadata") or {}; name = metadata.get("name"); namespace = metadata.get("namespace", a.namespace)
            client.validate_name(name); client.validate_name(namespace, "namespace")
            if namespace != a.namespace:
                raise KubectlError("YAML 中的 namespace 必须与页面选择一致")
            targets.append(f"{item['kind']}/{name}")
            versions.update(await _version(client, a.context, namespace, item["kind"].lower(), name))
        normalized = yaml.safe_dump_all(documents, allow_unicode=True, sort_keys=False)
        dry = await client.run(a.context, ["-n", a.namespace, "apply", "--server-side", "--dry-run=server", "-f", "-", "-o", "yaml"], normalized, client.settings.harness_write_timeout_seconds)
        diff = await client.run(a.context, ["-n", a.namespace, "diff", "-f", "-"], normalized, client.settings.harness_write_timeout_seconds, {0, 1})
        return PreparedOperation(tool_name="k8s_apply_yaml", target=", ".join(targets), arguments={"context": a.context, "namespace": a.namespace}, yaml_content=normalized, yaml_sha256=hashlib.sha256(normalized.encode()).hexdigest(), dry_run_output=dry.stdout, diff_output=diff.stdout or "无差异", resource_versions=versions)

    return restart, scale, rollback, image, apply_yaml
