from pydantic import BaseModel


class GenerationMessage(BaseModel):
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
