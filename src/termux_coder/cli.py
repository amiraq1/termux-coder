from __future__ import annotations

import asyncio

from . import logo
from .config import Settings
from .core.agent import Agent
from .core.registry import ToolRegistry
from .providers.openai_compat import OpenAICompatProvider
from .tools import edit, fs, shell, todos, maptool, gittool
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
    return reg


def build_agent(settings: Settings, ui) -> Agent:
    provider = OpenAICompatProvider(
        settings.openai_api_key, settings.openai_base_url, settings.model
    )
    return Agent(settings, provider, build_registry(), ui)


async def cli_main(settings: Settings) -> None:
    logo.print_banner()
    logo.ctrl("ready", f"{settings.workspace.resolve()}  security={settings.security_mode}")

    ui = CliUI()
    agent = build_agent(settings, ui)

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
        try:
            await agent.run_turn(text)
        except Exception as exc:
            print(f"error: {exc}")
