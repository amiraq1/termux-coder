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
    text = await asyncio.to_thread(ctx.repomap.render_full, focus, refresh)
    return text or "empty map"
