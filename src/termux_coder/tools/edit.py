from __future__ import annotations

import shutil
from datetime import datetime

from . import patch as patchlib


async def apply_patch(args: dict, ctx) -> str:
    """
    مسار التعديل الوحيد في v0.1:
    read_file (إلزامي) → apply_patch → diff → approval → backup → write
    """
    rel_input = args.get("path") or ""
    patch_text = args.get("patch") or ""

    try:
        path = ctx.jail.check(rel_input)
        rel = ctx.jail.rel(path)
        blocks = patchlib.parse_blocks(patch_text)
    except Exception as exc:
        return f"patch error: {exc}"

    if path.exists():
        if rel not in ctx.state.read_files:
            return f"refused: you must read_file({rel}) before patching it"

        old = path.read_text(encoding="utf-8", errors="replace")
        try:
            new = patchlib.apply_blocks(old, blocks)
        except patchlib.PatchError as exc:
            return f"patch error: {exc}"
    else:
        # إنشاء ملف جديد فقط بكتل SEARCH فارغة
        if any(find.strip() for find, _ in blocks):
            return "file does not exist; use an empty SEARCH block to create it"
        old = ""
        new = "\n".join(replace for _, replace in blocks)

    diff = patchlib.make_diff(rel, old, new)

    approved = await ctx.ui.request_approval("patch", {"diff": diff, "path": rel})
    ctx.audit.log("patch_approval", path=rel, approved=approved)
    if not approved:
        return "user rejected the patch"

    if path.exists():
        ctx.settings.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        shutil.copy2(path, ctx.settings.backup_dir / f"{path.name}.{stamp}.bak")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")

    ctx.state.read_files.add(rel)
    ctx.state.applied_patches.append(rel)
    ctx.audit.log("patch_applied", path=rel)
    adds = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    rems = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
    await ctx.ui.on_event("patch_applied", path=rel, diff=diff, additions=adds, removals=rems)

    if rel.endswith(".py") and ctx.lsp is not None:
        try:
            await ctx.lsp.notify_change(path, new)
            problems = await ctx.lsp.diagnostics(path)
        except Exception:
            problems = []
        await ctx.ui.on_event(
            "lsp_diag", path=rel, count=len(problems),
            first=problems[0] if problems else "clean",
        )
        if problems:
            return (
                f"patch applied to {rel}\nLSP diagnostics:\n" + "\n".join(problems[:10])
            )

    return f"patch applied to {rel}"
