from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent0.executors.base import Executor


class Tool(ABC):
    name: str
    description: str
    parameters: dict[str, Any]
    terminate: bool = False

    @abstractmethod
    def run(self, executor: Executor, arguments: dict[str, Any]) -> str:
        raise NotImplementedError

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registration order is the send order. Do not shuffle."""

    def __init__(self, tools: list[Tool]) -> None:
        self._tools = list(tools)
        names = [tool.name for tool in self._tools]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate tool names: {names}")

    def get(self, name: str) -> Tool:
        for tool in self._tools:
            if tool.name == name:
                return tool
        raise KeyError(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools]

    def names(self) -> list[str]:
        return [tool.name for tool in self._tools]
