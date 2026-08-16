from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

Handler = Callable[[dict, Any], Awaitable[str]]


@dataclass
class Tool:
    schema: dict
    handler: Handler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, name: str, description: str, parameters: dict, handler: Handler) -> None:
        self._tools[name] = Tool(
            schema={
                "type": "function",
                "function": {"name": name, "description": description, "parameters": parameters},
            },
            handler=handler,
        )

    def schemas(self) -> list[dict]:
        return [t.schema for t in self._tools.values()]

    def handler(self, name: str) -> Handler | None:
        tool = self._tools.get(name)
        return tool.handler if tool else None
