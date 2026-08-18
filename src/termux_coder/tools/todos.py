from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from typing import List

class TodoItem(BaseModel):
    text: str
    done: bool

class UpdateTodosArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: List[TodoItem]

async def update_todos(args: UpdateTodosArgs, ctx) -> str:
    items = args.items or []
    ctx.state.todos = [
        {"text": str(i.text), "done": bool(i.done)}
        for i in items
    ][:50]
    await ctx.ui.on_event("todos_update", items=ctx.state.todos)
    return "todos updated"
