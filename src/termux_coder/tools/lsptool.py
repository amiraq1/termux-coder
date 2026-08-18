from __future__ import annotations

from pydantic import BaseModel, ConfigDict

class LspDiagnosticsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str

async def lsp_diagnostics(args: LspDiagnosticsArgs, ctx) -> str:
    if ctx.lsp is None:
        return "lsp disabled"
    try:
        path = ctx.jail.check(args.path)
    except Exception as exc:
        return f"lsp error: {exc}"
    if not path.exists():
        return "file not found"

    text = path.read_text(encoding="utf-8", errors="replace")
    await ctx.lsp.notify_change(path, text)
    problems = await ctx.lsp.diagnostics(path)

    await ctx.ui.on_event(
        "lsp_diag", path=ctx.jail.rel(path), count=len(problems),
        first=problems[0] if problems else "clean",
    )
    return "\n".join(problems) or "no diagnostics"
