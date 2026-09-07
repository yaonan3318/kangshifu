"""安全调用 kubectl 的底层客户端。"""

import asyncio
import json
import re
import shutil
from dataclasses import dataclass

from app.config import Settings
from app.errors import AppError

K8S_NAME = re.compile(r"^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$")


class KubectlError(AppError):
    """可安全返回页面的 Kubernetes/Harness 校验或执行错误。"""
    def __init__(self, message: str, code: str = "KUBERNETES_ERROR", status_code: int = 400):
        super().__init__(code, message, status_code)


@dataclass(frozen=True)
class KubectlResult:
    stdout: str
    stderr: str
    returncode: int
    truncated: bool = False

    def json(self):
        try:
            return json.loads(self.stdout)
        except json.JSONDecodeError as exc:
            raise KubectlError("kubectl 没有返回有效 JSON") from exc


class KubectlClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def available(self) -> bool:
        return shutil.which("kubectl") is not None

    def validate_context(self, context: str) -> None:
        if context not in self.settings.allowed_k8s_contexts:
            raise KubectlError("Kubernetes context 未在配置白名单中")

    @staticmethod
    def validate_name(value: str, label: str = "资源名称") -> None:
        if not value or not K8S_NAME.fullmatch(value):
            raise KubectlError(f"{label}格式无效")

    async def run(self, context: str, args: list[str], stdin: str | None = None, timeout: int | None = None, accepted_codes: set[int] | None = None) -> KubectlResult:
        self.validate_context(context)
        if not self.available:
            raise KubectlError("未找到 kubectl，请先安装并配置 kubeconfig")
        process = await asyncio.create_subprocess_exec(
            "kubectl", "--context", context, *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(stdin.encode() if stdin is not None else None), timeout=timeout or self.settings.harness_read_timeout_seconds)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise KubectlError("kubectl 执行超时") from exc
        out, err = stdout.decode(errors="replace"), stderr.decode(errors="replace")
        maximum = self.settings.harness_max_tool_output_chars
        truncated = len(out) > maximum or len(err) > maximum
        result = KubectlResult(out[:maximum], err[:maximum], process.returncode, truncated)
        if result.returncode not in (accepted_codes or {0}):
            raise KubectlError(result.stderr.strip() or f"kubectl 执行失败（{result.returncode}）")
        return result
