from __future__ import annotations

import asyncio
import time

from . import logo
from openai import AuthenticationError
from .config import Settings
from .core.agent import Agent
from .core.registry import ToolRegistry
from .core.session import SessionStore
from .providers.openai_compat import OpenAICompatProvider
from .tools import edit, fs, shell, todos, maptool, gittool, lsptool
from .ui.cli import CliUI


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        "list_dir",
        "List files and directories under the workspace.",
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": []},
        fs.list_dir,
    )
    reg.register(
        "read_file",
        "Read a file. MUST be called before apply_patch on the same file.",
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        fs.read_file,
    )
    reg.register(
        "search_text",
        "grep search across workspace files.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}, "path": {"type": "string"}},
            "required": ["query"],
        },
        fs.search_text,
    )
    reg.register(
        "apply_patch",
        "Modify or create a file using SEARCH/REPLACE blocks. Shows a diff and requires human approval.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}, "patch": {"type": "string"}},
            "required": ["path", "patch"],
        },
        edit.apply_patch,
    )
    reg.register(
        "run_command",
        "Run a shell command inside the workspace. Requires human approval.",
        {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
        shell.run_command,
    )
    reg.register(
        "update_todos",
        "Maintain a visible task checklist for the current mission.",
        {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "done": {"type": "boolean"},
                        },
                        "required": ["text", "done"],
                    },
                }
            },
            "required": ["items"],
        },
        todos.update_todos,
    )
    reg.register(
        "repo_map",
        "Return the project symbol map. focus narrows to a file/symbol; refresh=true rescans.",
        {
            "type": "object",
            "properties": {"focus": {"type": "string"}, "refresh": {"type": "boolean"}},
            "required": [],
        },
        maptool.repo_map,
    )
    reg.register("git_status", "Show git branch and porcelain status.",
        {"type": "object", "properties": {}, "required": []}, gittool.git_status)
    reg.register("git_diff", "Unified diff of the working tree (staged=true for index).",
        {"type": "object", "properties": {"staged": {"type": "boolean"}}, "required": []}, gittool.git_diff)
    reg.register("git_log", "Last 10 commits, oneline.",
        {"type": "object", "properties": {}, "required": []}, gittool.git_log)
    reg.register("git_init", "Initialize a git repository in the workspace (approval).",
        {"type": "object", "properties": {}, "required": []}, gittool.git_init)
    reg.register("git_checkpoint", "Commit the current state as a safety checkpoint (approval).",
        {"type": "object", "properties": {}, "required": []}, gittool.git_checkpoint)
    reg.register("git_commit", "Commit all changes with a concise message (approval). Message is auto-prefixed 'agent:'.",
        {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}, gittool.git_commit)
    reg.register("git_restore", "Discard changes to workspace-relative paths (approval, destructive).",
        {"type": "object", "properties": {"paths": {"type": "array", "items": {"type": "string"}}}, "required": ["paths"]}, gittool.git_restore)
    reg.register(
        "lsp_diagnostics",
        "Return current LSP diagnostics for a Python file.",
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        lsptool.lsp_diagnostics,
    )
    return reg


def build_agent(settings: Settings, ui, store=None, resume_id=None) -> Agent:
    provider = OpenAICompatProvider(
        settings.openai_api_key, settings.openai_base_url, settings.model
    )
    return Agent(settings, provider, build_registry(), ui, store=store, resume_id=resume_id)


async def cli_main(settings: Settings) -> None:
    logo.print_banner()
    logo.ctrl("ready", f"{settings.workspace.resolve()}  security={settings.security_mode}")

    ui = CliUI()
    store = SessionStore(settings.state_dir / "sessions.db")
    try:
        agent = build_agent(settings, ui, store=store)
    except RuntimeError as exc:
        import sys
        sys.exit(exc)
    logo.ctrl("session", f"{agent.session_id}{' · resumed' if agent.resumed else ' · new'}")

    while True:
        try:
            text = await asyncio.get_running_loop().run_in_executor(
                None, input, f"\n{logo.paint('you', logo.DIM)} ❯ "
            )
        except (EOFError, KeyboardInterrupt):
            break
        text = text.strip()
        if not text:
            continue
        if text in {"/exit", "exit", "quit"}:
            break

        if text == "/sessions":
            for s in store.list_recent():
                when = time.strftime("%m-%d %H:%M", time.localtime(s["updated_at"]))
                marker = " ◀" if s["id"] == agent.session_id else ""
                print(f"{s['id']}  {when}  {s['title']}{marker}")
            continue

        if text == "/new":
            agent = build_agent(settings, ui, store=store)
            logo.ctrl("session", f"{agent.session_id} · new")
            continue

        if text == "/resume" or text.startswith("/resume "):
            parts = text.split()
            arg = parts[1] if len(parts) > 1 else None
            recents = store.list_recent()
            if arg:
                pick = next((s for s in recents if s["id"].startswith(arg)), None)
            else:
                others = [s for s in recents if s["id"] != agent.session_id]
                pick = others[0] if others else None
            if not pick:
                print("no session to resume")
                continue
            agent = build_agent(settings, ui, store=store, resume_id=pick["id"])
            logo.ctrl("session", f"{agent.session_id} · resumed ({len(agent.messages) - 1} messages)")
            continue

        try:
            await agent.run_turn(text)
        except AuthenticationError:
            print(logo.paint("خطأ مصادقة: مفتاح API غير صحيح أو غير مُحمّل.", logo.TEAL))
            print("شغّل: source ~/termux-coder/env_nvidia.sh")
        except Exception as exc:
            print(f"error: {exc}")

    await agent.close()
