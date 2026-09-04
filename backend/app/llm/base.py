"""大模型适配层的公共消息结构和可分类异常。"""

from pydantic import BaseModel


class GenerationMessage(BaseModel):
    """兼容 Chat Completions 风格的单条 system/user/assistant 消息。"""
    role: str
    content: str


class LlmError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class LlmUnavailable(LlmError):
    pass


class LlmTimeout(LlmError):
    pass


class LlmRateLimited(LlmError):
    pass


class LlmAuthenticationFailed(LlmError):
    pass
