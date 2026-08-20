from __future__ import annotations

import asyncio
from pydantic import BaseModel, ConfigDict
from typing import Optional

class RepoMapArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    focus: Optional[str] = None
    refresh: Optional[bool] = False

async def repo_map(args: RepoMapArgs, ctx) -> str:
    focus = (args.focus or "").strip()
    refresh = bool(args.refresh)
    timeout_s = getattr(ctx.settings, "repo_map_timeout", 30)

    await ctx.ui.on_event("repo_map_start", timeout_s=timeout_s)

    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(ctx.repomap.render_full, focus, refresh),
            timeout=timeout_s
        )
        await ctx.ui.on_event("map_ready", **getattr(ctx.repomap, "last_stats", {}))
        return text or "empty map"
    except asyncio.TimeoutError:
        await ctx.ui.on_event("repo_map_timeout", timeout_s=timeout_s, reason="repository scan exceeded its time budget")
        return "repo_map timed out"
    except Exception as e:
        await ctx.ui.on_event("repo_map_failed", error=str(e))
        return f"repo_map failed: {e}"
