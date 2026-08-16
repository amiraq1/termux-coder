from __future__ import annotations


async def update_todos(args: dict, ctx) -> str:
    items = args.get("items") or []
    ctx.state.todos = [
        {"text": str(i.get("text", "")), "done": bool(i.get("done"))}
        for i in items
    ][:50]
    await ctx.ui.on_event("todos_update", items=ctx.state.todos)
    return "todos updated"
