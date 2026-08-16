from __future__ import annotations

import asyncio


async def repo_map(args: dict, ctx) -> str:
    focus = (args.get("focus") or "").strip()
    refresh = bool(args.get("refresh"))
    text = await asyncio.to_thread(ctx.repomap.render_full, focus, refresh)
    return text or "empty map"
