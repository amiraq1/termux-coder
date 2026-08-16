from __future__ import annotations

import asyncio
import subprocess

from ..security.jail import WorkspaceJail  # noqa: F401  (typing clarity)

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".termux_coder", ".cache"}


async def list_dir(args: dict, ctx) -> str:
    path = ctx.jail.check(args.get("path") or ".")
    if not path.exists():
        return f"not found: {args.get('path')}"
    if path.is_file():
        return "path is a file"
    entries = []
    for entry in sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        if entry.is_dir() and entry.name in SKIP_DIRS:
            continue
        entries.append(("dir  " if entry.is_dir() else "file ") + ctx.jail.rel(entry))
    return "\n".join(entries[:500]) or "empty"


async def read_file(args: dict, ctx) -> str:
    path = ctx.jail.check(args["path"])
    if not path.exists():
        return f"not found: {args['path']}"
    if path.is_dir():
        return "path is a directory"
    if path.stat().st_size > 2_000_000:
        return "file too large"
    text = path.read_text(encoding="utf-8", errors="replace")
    # تسجيل القراءة: شرط إلزامي قبل أي apply_patch على هذا الملف
    ctx.state.read_files.add(ctx.jail.rel(path))
    await ctx.ui.on_event("read_ok", path=ctx.jail.rel(path), lines=text.count("\n") + 1)
    return text[: ctx.settings.max_file_chars]


async def search_text(args: dict, ctx) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "empty query"
    root = ctx.jail.check(args.get("path") or ".")
    cmd = [
        "grep", "-RIn",
        "--exclude-dir=.git", "--exclude-dir=node_modules", "--exclude-dir=.venv",
        "--", query, str(root),
    ]
    proc = await asyncio.to_thread(
        subprocess.run, cmd, capture_output=True, text=True, timeout=60
    )
    return proc.stdout[: ctx.settings.max_output_chars] or "no matches"
