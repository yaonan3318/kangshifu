"""本地 Ollama HTTP 客户端，用于调用 qwen3:8b 并解析流式响应。"""

import json
from collections.abc import AsyncIterator

import httpx

from app.config import Settings
from app.llm.base import GenerationMessage, LlmTimeout, LlmUnavailable
from app.schemas.answer import OllamaStatus


class OllamaClient:
    """封装 Ollama 状态探测和聊天生成，避免 RAG 层依赖具体 HTTP 格式。"""
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.ollama_base_url.rstrip("/")

    async def status(self) -> OllamaStatus:
        """探测 Ollama 服务是否可达以及配置的模型是否已经下载。"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            names = {item.get("name", "") for item in response.json().get("models", [])}
            requested = self.settings.ollama_model
            installed = requested in names or any(name.split(":")[0] == requested for name in names)
            return OllamaStatus(reachable=True, model=requested, installed=installed)
        except (httpx.HTTPError, ValueError):
            return OllamaStatus(reachable=False, model=self.settings.ollama_model, installed=False)

    async def stream(self, messages: list[GenerationMessage]) -> AsyncIterator[str]:
        """逐段返回本地模型输出；keep_alive=0 会在回答后释放模型运行内存。"""
        payload = {
            "model": self.settings.ollama_model,
            "messages": [message.model_dump() for message in messages],
            "stream": True,
            "think": False,
            "keep_alive": self.settings.ollama_keep_alive,
            "options": {"temperature": 0.2},
        }
        timeout = httpx.Timeout(self.settings.ollama_timeout_seconds, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise LlmUnavailable("OLLAMA_REQUEST_FAILED", "千问本地模型调用失败，请检查 Ollama 日志")
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield content
        except httpx.TimeoutException as exc:
            raise LlmTimeout("OLLAMA_TIMEOUT", "千问本地模型响应超时") from exc
        except httpx.ConnectError as exc:
            raise LlmUnavailable("OLLAMA_UNAVAILABLE", "无法连接 Ollama，请先启动 Ollama") from exc
        except (json.JSONDecodeError, httpx.HTTPError) as exc:
            raise LlmUnavailable("OLLAMA_INVALID_RESPONSE", "千问本地模型返回异常") from exc
