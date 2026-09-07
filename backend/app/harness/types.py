"""Harness 内部的严格数据类型。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HarnessDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["call_tool", "final_answer"]
    tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=1000)
    answer: str | None = None

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "call_tool" and not self.tool:
            raise ValueError("call_tool requires tool")
        if self.action == "final_answer" and not self.answer:
            raise ValueError("final_answer requires answer")
        return self


class ToolResult(BaseModel):
    summary: str
    data: Any = None
    truncated: bool = False


class PreparedOperation(BaseModel):
    tool_name: str
    target: str
    arguments: dict[str, Any]
    yaml_content: str | None = None
    yaml_sha256: str | None = None
    dry_run_output: str | None = None
    diff_output: str | None = None
    resource_versions: dict[str, str] = Field(default_factory=dict)
