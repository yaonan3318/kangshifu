import json
from collections.abc import AsyncIterator

import httpx

from app.config import Settings
from app.llm.base import GenerationMessage, LlmAuthenticationFailed, LlmRateLimited, LlmTimeout, LlmUnavailable


class DeepSeekClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.deepseek_base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.settings.deepseek_api_key.strip())

    async def stream(self, messages: list[GenerationMessage]) -> AsyncIterator[str]:
        if not self.configured:
            raise LlmUnavailable("DEEPSEEK_NOT_CONFIGURED", "尚未配置 DeepSeek API Key，本次使用本地模型回答。")
        payload = {
            "model": self.settings.deepseek_model,
            "messages": [message.model_dump() for message in messages],
            "stream": True,
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self.settings.deepseek_api_key}", "Content-Type": "application/json"}
        timeout = httpx.Timeout(self.settings.deepseek_timeout_seconds, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", f"{self.base_url}/chat/completions", headers=headers, json=payload) as response:
                    if response.status_code in (401, 403):
                        raise LlmAuthenticationFailed("DEEPSEEK_AUTH_FAILED", "DeepSeek API Key 无效，本次使用本地模型回答。")
                    if response.status_code == 429:
                        raise LlmRateLimited("DEEPSEEK_RATE_LIMITED", "DeepSeek 请求受限或余额不足，本次使用本地模型回答。")
                    if response.status_code >= 400:
                        raise LlmUnavailable("DEEPSEEK_REQUEST_FAILED", "DeepSeek 服务调用失败，本次使用本地模型回答。")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        data = json.loads(raw)
                        content = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if content:
                            yield content
        except httpx.TimeoutException as exc:
            raise LlmTimeout("DEEPSEEK_TIMEOUT", "DeepSeek 响应超时，本次使用本地模型回答。") from exc
        except httpx.ConnectError as exc:
            raise LlmUnavailable("DEEPSEEK_UNAVAILABLE", "无法连接 DeepSeek，本次使用本地模型回答。") from exc
        except (json.JSONDecodeError, httpx.HTTPError) as exc:
            raise LlmUnavailable("DEEPSEEK_INVALID_RESPONSE", "DeepSeek 返回异常，本次使用本地模型回答。") from exc
