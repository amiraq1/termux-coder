from __future__ import annotations

import asyncio
import hashlib
import subprocess

from ..security.jail import WorkspaceJail  # noqa: F401  (typing clarity)

from pydantic import BaseModel, ConfigDict
from typing import Optional

class ListDirArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: Optional[str] = None

class ReadFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str

class SearchTextArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str
    path: Optional[str] = None


SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".termux_coder", ".cache"}

MAX_BINARY_PROBE = 8192  # bytes to probe for binary detection


def _is_binary_bytes(data: bytes) -> bool:
    """كشف سريع للملفات الثنائية: null bytes في أول PROBE bytes."""
    return b"\x00" in data


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def list_dir(args: ListDirArgs, ctx) -> str:
    path = ctx.jail.check(args.path or ".")
    if not path.exists():
        return f"not found: {args.path}"
    if path.is_file():
        return "path is a file"
    entries = []
    for entry in sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        if entry.is_dir() and entry.name in SKIP_DIRS:
            continue
        entries.append(("dir  " if entry.is_dir() else "file ") + ctx.jail.rel(entry))
    return "\n".join(entries[:500]) or "empty"


async def read_file(args: ReadFileArgs, ctx) -> str:
    rel_input = args.path or ""

    # تطبيع المسار
    if rel_input.startswith("./"):
        rel_input = rel_input[2:]

    path = ctx.jail.check(rel_input)
    rel = ctx.jail.rel(path)

    # تحقق من التكرار
    if rel in ctx.state.read_files:
        return f"already_read: {rel} (use the content from context)"

    if not path.exists():
        return f"not found: {rel_input!r}"
    if path.is_dir():
        return "path is a directory"
    if not path.is_file():
        return f"not a regular file: {rel_input!r}"

    # فحص ثنائي مبكر
    try:
        with path.open("rb") as fh:
            probe = fh.read(MAX_BINARY_PROBE)
        if _is_binary_bytes(probe):
            return f"refused: binary file not supported: {rel}"
    except PermissionError:
        return f"permission denied: {rel}"

    stat_result = path.stat()
    if stat_result.st_size > 2_000_000:
        return "file too large (> 2 MB)"

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        return f"permission denied reading: {rel}"
    except IsADirectoryError:
        return f"path is a directory: {rel}"
    except OSError as exc:
        return f"read error: {exc}"

    # ── تسجيل القراءة + حفظ hash للكشف عن التغيير المتزامن ──
    ctx.state.read_files.add(rel)
    ctx.state.read_hashes[rel] = _sha256(text)
    await ctx.ui.on_event("read_ok", path=rel, lines=text.count("\n") + 1)
    return text[: ctx.settings.max_file_chars]


async def search_text(args: SearchTextArgs, ctx) -> str:
    query = (args.query or "").strip()
    if not query:
        return "empty query"
    root = ctx.jail.check(args.path or ".")
    cmd = [
        "grep", "-RIn",
        "--exclude-dir=.git", "--exclude-dir=node_modules", "--exclude-dir=.venv",
        "--", query, str(root),
    ]
    proc = await asyncio.to_thread(
        subprocess.run, cmd, capture_output=True, text=True, timeout=60
    )
    return proc.stdout[: ctx.settings.max_output_chars] or "no matches"
