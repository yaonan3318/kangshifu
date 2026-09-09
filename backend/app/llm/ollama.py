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

    async def warmup(self) -> bool:
        """发送一次极短请求把模型载入显存/内存，减少首次问答等待。"""
        messages = [
            GenerationMessage(role="system", content="请只回复两个字：就绪。"),
            GenerationMessage(role="user", content="预热"),
        ]
        try:
            async for item in self.stream_with_stats(messages):
                if item.get("delta"):
                    return True
            return True
        except LlmError:
            return False

    async def stream_with_stats(self, messages: list[GenerationMessage]):
        """与 stream 相同，但逐段附带 Ollama 统计信息（token 数、done 标记）。"""
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
                        yield {
                            "delta": data.get("message", {}).get("content", ""),
                            "prompt_eval_count": data.get("prompt_eval_count"),
                            "eval_count": data.get("eval_count"),
                            "done": bool(data.get("done")),
                        }
        except httpx.TimeoutException as exc:
            raise LlmTimeout("OLLAMA_TIMEOUT", "千问本地模型响应超时") from exc
        except httpx.ConnectError as exc:
            raise LlmUnavailable("OLLAMA_UNAVAILABLE", "无法连接 Ollama，请先启动 Ollama") from exc
        except (json.JSONDecodeError, httpx.HTTPError) as exc:
            raise LlmUnavailable("OLLAMA_INVALID_RESPONSE", "千问本地模型返回异常") from exc

    async def stream(self, messages: list[GenerationMessage]) -> AsyncIterator[str]:
        """逐段返回本地模型输出；keep_alive 决定回答结束后模型是否驻留内存。"""
        async for item in self.stream_with_stats(messages):
            if item["delta"]:
                yield item["delta"]

    async def complete_json(self, messages: list[GenerationMessage]) -> dict:
        """要求 Ollama 返回单个 JSON 对象，供 Harness 解析工具决策。"""
        payload = {
            "model": self.settings.ollama_model,
            "messages": [message.model_dump() for message in messages],
            "stream": False, "format": "json", "think": False,
            "keep_alive": self.settings.ollama_keep_alive,
            "options": {"temperature": 0.1},
        }
        timeout = httpx.Timeout(self.settings.ollama_timeout_seconds, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
            content = response.json().get("message", {}).get("content", "")
            value = json.loads(content)
            if not isinstance(value, dict):
                raise ValueError("decision must be an object")
            return value
        except httpx.TimeoutException as exc:
            raise LlmTimeout("OLLAMA_TIMEOUT", "千问本地模型响应超时") from exc
        except httpx.ConnectError as exc:
            raise LlmUnavailable("OLLAMA_UNAVAILABLE", "无法连接 Ollama，请先启动 Ollama") from exc
        except (ValueError, json.JSONDecodeError, httpx.HTTPError) as exc:
            raise LlmUnavailable("OLLAMA_INVALID_RESPONSE", "千问没有返回有效的 Harness 决策") from exc
