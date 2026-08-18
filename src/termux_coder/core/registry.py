from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

Handler = Callable[[Any, Any], Awaitable[str]]


@dataclass
class Tool:
    schema: dict
    handler: Handler
    model: type[BaseModel]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, name: str, description: str, args_model: type[BaseModel], handler: Handler) -> None:
        self._tools[name] = Tool(
            schema={
                "type": "function",
                "function": {
                    "name": name, 
                    "description": description, 
                    "parameters": args_model.model_json_schema()
                },
            },
            handler=handler,
            model=args_model,
        )

    def schemas(self, exclude: set[str] | None = None) -> list[dict]:
        exclude = exclude or set()
        return [t.schema for name, t in self._tools.items() if name not in exclude]

    def handler(self, name: str) -> Handler | None:
        tool = self._tools.get(name)
        if not tool:
            return None

        async def wrapper(raw_args: dict, ctx: Any) -> str:
            args = tool.model.model_validate(raw_args)
            return await tool.handler(args, ctx)

        return wrapper
