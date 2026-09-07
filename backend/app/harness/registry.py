"""白名单工具注册表及参数校验。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.harness.types import PreparedOperation, ToolResult

ToolHandler = Callable[[BaseModel], Awaitable[ToolResult | PreparedOperation]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    arguments_model: type[BaseModel]
    read_only: bool
    handler: ToolHandler


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"duplicate tool: {definition.name}")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ValueError(f"unknown tool: {name}") from exc

    def validate(self, name: str, arguments: dict[str, Any]) -> BaseModel:
        return self.get(name).arguments_model.model_validate(arguments)

    def catalog(self) -> list[dict[str, Any]]:
        return [{
            "name": item.name, "description": item.description, "read_only": item.read_only,
            "parameters": item.arguments_model.model_json_schema(),
        } for item in self._tools.values()]
