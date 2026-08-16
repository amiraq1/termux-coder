from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path


class GitError(Exception):
    pass


def run_git(root: Path, args: list[str], timeout: int = 30) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise GitError(
            proc.stderr.strip() or proc.stdout.strip() or f"git exit {proc.returncode}"
        )
    return proc.stdout


def is_repo(root: Path) -> bool:
    try:
        run_git(root, ["rev-parse", "--is-inside-work-tree"])
        return True
    except (GitError, FileNotFoundError):
        return False


async def _git(ctx, args: list[str]) -> str:
    return await asyncio.to_thread(run_git, ctx.jail.root, args)


def _not_repo() -> str:
    return "not a git repository. Propose git_init to the user."


def _clean_message(message: str) -> str:
    m = " ".join(str(message).split())[:200]
    if not m:
        m = "update"
    if not m.startswith(("agent:", "checkpoint:")):
        m = f"agent: {m}"
    return m


# ── قراءة فقط ──────────────────────────────────────────────
async def git_status(args: dict, ctx) -> str:
    if not await asyncio.to_thread(is_repo, ctx.jail.root):
        return _not_repo()
    out = await _git(ctx, ["status", "--porcelain=v1", "--branch"])
    lines = [l for l in out.splitlines() if l]
    branch = lines[0][3:].strip() if lines and lines[0].startswith("##") else ""
    changes = len([l for l in lines if not l.startswith("##")])
    await ctx.ui.on_event("git_info", label="status", detail=f"{branch} · {changes} changed")
    return out or "clean working tree"


async def git_diff(args: dict, ctx) -> str:
    if not await asyncio.to_thread(is_repo, ctx.jail.root):
        return _not_repo()
    cmd = ["diff", "--no-color"]
    if args.get("staged"):
        cmd.append("--staged")
    out = await _git(ctx, cmd)
    if out:
        await ctx.ui.on_event("git_diff_view", diff=out)
    return out[: ctx.settings.max_output_chars] or "no diff"


async def git_log(args: dict, ctx) -> str:
    if not await asyncio.to_thread(is_repo, ctx.jail.root):
        return _not_repo()
    out = await _git(ctx, ["log", "--oneline", "-n", "10"])
    return out or "no commits yet"


# ── عمليات معدِّلة (موافقة إلزامية) ──────────────────────────
async def git_init(args: dict, ctx) -> str:
    approved = await ctx.ui.request_approval(
        "git",
        {"title": "Initialize git repository?", "body": f"git init in {ctx.jail.root}"},
    )
    ctx.audit.log("git_init", approved=approved)
    if not approved:
        return "user rejected git init"

    out = await _git(ctx, ["init"])

    # هوية احتياطية حتى لا يفشل الالتزام على هاتف بدون إعداد git
    try:
        await _git(ctx, ["config", "user.email"])
    except GitError:
        await _git(ctx, ["config", "user.email", "agent@termux-coder.local"])
        await _git(ctx, ["config", "user.name", "termux-coder"])

    await ctx.ui.on_event("git_info", label="init", detail="repository created")
    return out.strip() or "initialized"


async def git_checkpoint(args: dict, ctx) -> str:
    if not await asyncio.to_thread(is_repo, ctx.jail.root):
        return _not_repo()

    status = await _git(ctx, ["status", "--porcelain=v1"])
    if not status.strip():
        return "working tree clean; nothing to checkpoint"

    message = f"checkpoint: before agent task {time.strftime('%Y%m%d-%H%M%S')}"
    approved = await ctx.ui.request_approval(
        "git", {"title": "Create checkpoint commit?", "body": f"{message}\n\n{status[:1500]}"}
    )
    ctx.audit.log("git_checkpoint", approved=approved)
    if not approved:
        return "user rejected checkpoint"

    await _git(ctx, ["add", "-A"])
    await _git(ctx, ["commit", "-m", message])
    h = (await _git(ctx, ["rev-parse", "--short", "HEAD"])).strip()
    await ctx.ui.on_event("git_info", label="checkpoint", detail=h)
    return f"checkpoint {h} created"


async def git_commit(args: dict, ctx) -> str:
    if not await asyncio.to_thread(is_repo, ctx.jail.root):
        return _not_repo()

    message = _clean_message(args.get("message", ""))
    status = await _git(ctx, ["status", "--porcelain=v1"])
    if not status.strip():
        return "working tree clean; nothing to commit"

    approved = await ctx.ui.request_approval(
        "git", {"title": "Create commit?", "body": f"{message}\n\n{status[:1200]}"}
    )
    ctx.audit.log("git_commit", message=message, approved=approved)
    if not approved:
        return "user rejected commit"

    await _git(ctx, ["add", "-A"])
    await _git(ctx, ["commit", "-m", message])
    h = (await _git(ctx, ["rev-parse", "--short", "HEAD"])).strip()
    await ctx.ui.on_event("git_info", label="commit", detail=f"{h} · {message}")
    return f"committed {h}: {message}"


async def git_restore(args: dict, ctx) -> str:
    if not await asyncio.to_thread(is_repo, ctx.jail.root):
        return _not_repo()

    paths = args.get("paths") or []
    if not paths:
        return "no paths given"

    checked: list[str] = []
    for p in paths:
        try:
            checked.append(ctx.jail.rel(ctx.jail.check(p)))
        except Exception as exc:
            return f"restore error: {exc}"

    approved = await ctx.ui.request_approval(
        "git", {"title": "Restore (discard changes)?", "body": "\n".join(checked)}
    )
    ctx.audit.log("git_restore", paths=checked, approved=approved)
    if not approved:
        return "user rejected restore"

    await _git(ctx, ["restore", "--", *checked])
    await ctx.ui.on_event("git_info", label="restore", detail=", ".join(checked), danger=True)
    return f"restored: {', '.join(checked)}"
