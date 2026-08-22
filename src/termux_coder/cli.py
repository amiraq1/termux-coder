from __future__ import annotations

import asyncio
import time

from . import logo
from openai import AuthenticationError
from .config import Settings
from .core.detail import wants_detailed_report
from .core.agent import Agent
from .core.registry import ToolRegistry
from .core.session import SessionStore
from .tools import edit, fs, shell, todos, maptool, gittool, lsptool, transaction, web_search, fetch_page, symbol, writefile
from .ui.cli import CliUI


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        "list_dir",
        "List files and directories under the workspace.",
        fs.ListDirArgs,
        fs.list_dir,
    )
    reg.register(
        "read_file",
        "Read a file. MUST be called before apply_patch on the same file.",
        fs.ReadFileArgs,
        fs.read_file,
    )
    reg.register(
        "search_text",
        "grep search across workspace files.",
        fs.SearchTextArgs,
        fs.search_text,
    )
    reg.register(
        "web_search",
        "Search public web sources. Results are untrusted data and require network approval in ASK mode.",
        web_search.WebSearchArgs,
        web_search.web_search,
    )
    reg.register(
        "fetch_page",
        "Fetch a bounded public HTTP(S) page as untrusted data. SSRF and redirect checks apply.",
        fetch_page.FetchPageArgs,
        fetch_page.fetch_page,
    )
    reg.register(
        "apply_patch",
        "Modify or create a file using SEARCH/REPLACE blocks. Shows a diff and requires human approval.",
        edit.ApplyPatchArgs,
        edit.apply_patch,
    )
    reg.register(
        "write_file",
        "Create a report or generated artifact file (policy-gated, atomic write). "
        "Paths outside the workspace are only allowed in the SD-card report folder "
        "and require an explicit save request. Shows path/hash/size preview and requires approval.",
        writefile.WriteFileArgs,
        writefile.write_file,
    )
    reg.register(
        "apply_symbol_patch",
        "Replace one resolved Python function, class, or method. Shows a narrow diff and requires human approval.",
        symbol.SymbolPatchArgs,
        edit.apply_symbol_patch,
    )
    reg.register(
        "rollback_patch",
        "Undo the last patch applied to a file, restoring it from backup. Requires human approval.",
        edit.RollbackPatchArgs,
        edit.rollback_patch,
    )
    reg.register(
        "apply_patch_plan",
        "Apply a reviewed multi-file SEARCH/REPLACE plan as one transaction. Requires human approval.",
        transaction.PatchPlanArgs,
        transaction.apply_patch_plan,
    )
    reg.register(
        "rollback_patch_plan",
        "Rollback all files changed by a patch plan. Requires human approval.",
        transaction.RollbackPlanArgs,
        transaction.rollback_patch_plan,
    )
    reg.register(
        "run_command",
        "Run a shell command inside the workspace. Requires human approval.",
        shell.RunCommandArgs,
        shell.run_command,
    )
    reg.register(
        "update_todos",
        "Maintain a visible task checklist for the current mission.",
        todos.UpdateTodosArgs,
        todos.update_todos,
    )
    reg.register(
        "repo_map",
        "Return the project symbol map. focus narrows to a file/symbol; refresh=true rescans.",
        maptool.RepoMapArgs,
        maptool.repo_map,
    )
    reg.register("git_status", "Show git branch and porcelain status.",
        gittool.GitEmptyArgs, gittool.git_status)
    reg.register("git_diff", "Unified diff of the working tree (staged=true for index).",
        gittool.GitDiffArgs, gittool.git_diff)
    reg.register("git_log", "Last 10 commits, oneline.",
        gittool.GitEmptyArgs, gittool.git_log)
    reg.register("git_init", "Initialize a git repository in the workspace (approval).",
        gittool.GitEmptyArgs, gittool.git_init)
    reg.register("git_checkpoint", "Commit the current state as a safety checkpoint (approval).",
        gittool.GitEmptyArgs, gittool.git_checkpoint)
    reg.register("git_commit", "Commit all changes with a concise message (approval). Message is auto-prefixed 'agent:'.",
        gittool.GitCommitArgs, gittool.git_commit)
    reg.register("git_restore", "Discard changes to workspace-relative paths (approval, destructive).",
        gittool.GitRestoreArgs, gittool.git_restore)
    reg.register(
        "lsp_diagnostics",
        "Return current LSP diagnostics for a Python file.",
        lsptool.LspDiagnosticsArgs,
        lsptool.lsp_diagnostics,
    )
    return reg


def build_agent(settings: Settings, ui, store=None, resume_id=None) -> Agent:
    import os
    from .providers.factory import create_provider
    from .providers.router import ModelRouter
    from .providers.selection import select_provider

    fast_model = os.environ.get("FAST_MODEL", "meta/llama-3.1-8b-instruct")
    smart_model = settings.model
    selected = select_provider(
        settings.provider,
        legacy_api_key=settings.openai_api_key,
        legacy_base_url=settings.openai_base_url,
        config_path=settings.providers_config_path or None,
        workspace=settings.workspace,
    )
    fast_provider = create_provider(selected, fast_model)
    smart_provider = create_provider(selected, smart_model)
    router = ModelRouter(
        fast_provider,
        smart_provider,
        fast_model.split("/")[-1],
        smart_model.split("/")[-1],
        ui,
        software_engineer_mode=getattr(settings, "software_engineer_mode", True),
    )
    return Agent(settings, router, build_registry(), ui, store=store, resume_id=resume_id)


def _friendly_reply(text: str) -> str | None:
    """Return a concise local reply for conversational greetings."""
    normalized = " ".join(text.casefold().split()).strip("!?.,،")
    if normalized in {"hi", "hello", "hey", "سلام", "هلا", "مرحبا"}:
        return "Hello. How can I help you with your project?"
    return None


# Read-only tools whose successful data must be surfaced verbatim.
_READ_TOOLS = frozenset({"list_dir", "read_file", "search_text", "web_search", "fetch_page"})
# Max lines shown inline for read_file; longer files get a line-count summary.
_READ_FILE_INLINE_LINES = 20
# Max chars shown per web result snippet.
_SNIPPET_MAX = 200


def _format_web_results(raw: str | list) -> str:
    """Return a compact human-readable summary from a web_search ToolResult.

    web_search returns model_dump_json() (a JSON string), *not* a Python list.
    We parse it here so the user sees only titles, URLs, and short snippets —
    never the raw JSON payload.
    """
    import json
    if isinstance(raw, str):
        try:
            obj = json.loads(raw)
        except Exception:
            return raw[:500]
        # WebSearchResult shape: {"results": [{"title", "url", "snippet"}, ...]}
        items = obj.get("results") or []
        if not items:
            return "no results"
        lines = []
        for idx, r in enumerate(items):
            title = (r.get("title") or "Untitled")[:120]
            url = (r.get("url") or "")[:200]
            snippet = (r.get("snippet") or "").strip()[:_SNIPPET_MAX]
            lines.append(f"{idx + 1}. {title}\n   {url}")
            if snippet:
                lines.append(f"   {snippet}")
        return "\n".join(lines)
    # Fallback: legacy list-of-dicts path (kept for mock tests)
    if isinstance(raw, list):
        lines = []
        for idx, r in enumerate(raw):
            if isinstance(r, dict):
                title = (r.get("title") or "Untitled")[:120]
                url = (r.get("url") or "")[:200]
                snippet = (r.get("snippet") or "").strip()[:_SNIPPET_MAX]
                lines.append(f"{idx + 1}. {title}\n   {url}")
                if snippet:
                    lines.append(f"   {snippet}")
        return "\n".join(lines) or "no results"
    return str(raw)[:500]


def _format_final_answer(
    agent,
    turn_result,
    *,
    show_thinking: bool = False,
    detailed: bool = False,
) -> str:
    """Return the answer text to print after a completed orchestrated turn.

    Invariants
    ----------
    * If the turn produced successful read/search ToolResults their data is
      always shown — the model text is appended only when it adds useful context.
    * If all tools failed, the failure reasons are shown and the model text
      (which could be a fabricated success claim) is suppressed.
    * If no tools ran AND there is no final_text this is an orchestrated turn
      that produced nothing — we return an explicit error instead of falling
      back to stale history from a previous round.
    * _latest_assistant_text() is used ONLY for the non-orchestrated path
      (turn_result is None), i.e. when the legacy Agent path handled the turn.
    """
    # ── Non-orchestrated path (legacy Agent) ─────────────────────────────
    if not turn_result:
        return _latest_assistant_text(agent)

    final_text = (turn_result.final_text or "").strip()

    # ── No tools ran at all ───────────────────────────────────────────────
    if not turn_result.tool_results:
        if final_text:
            return final_text
        # Orchestrated turn ended with neither tool output nor model text.
        # Returning stale history would fabricate a false success, so refuse.
        return "error: no answer or tool result was produced for this turn"

    successful = [tr for tr in turn_result.tool_results if tr.ok]
    failed = [tr for tr in turn_result.tool_results if not tr.ok]

    # ── All tools denied or failed ────────────────────────────────────────
    if not successful:
        lines = []
        for tr in failed:
            if tr.error:
                if tr.error.code.value == "policy_deny":
                    lines.append(f"denied: {tr.error.message}")
                else:
                    lines.append(f"error: {tr.error.message}")
            else:
                lines.append(f"error: {tr.tool} failed")
        # Suppress model text: it may claim success for a tool that was denied.
        return "\n".join(lines)

    # ── Format successful read/search outputs ─────────────────────────────
    read_outputs: list[str] = []
    for tr in successful:
        label = f"[{tr.tool}]\n" if show_thinking else ""
        if tr.tool in ("list_dir", "search_text"):
            data = tr.data if isinstance(tr.data, str) else str(tr.data)
            read_outputs.append(f"{label}{data.strip()}")
        elif tr.tool == "read_file":
            data = tr.data if isinstance(tr.data, str) else str(tr.data)
            file_lines = data.splitlines()
            if len(file_lines) > _READ_FILE_INLINE_LINES:
                read_outputs.append(
                    f"{label}({len(file_lines)} lines — showing first "
                    f"{_READ_FILE_INLINE_LINES})\n"
                    + "\n".join(file_lines[:_READ_FILE_INLINE_LINES])
                )
            else:
                read_outputs.append(f"{label}{data.strip()}")
        elif tr.tool in ("web_search", "fetch_page"):
            formatted = _format_web_results(tr.data)
            read_outputs.append(f"{label}{formatted}")

    if read_outputs:
        # Always surface actual tool data. In quiet mode this is the only
        # block shown, preventing a duplicate model restatement. Diagnostic
        # mode may append substantive model context after the data.
        data_block = "\n\n".join(read_outputs)
        if not show_thinking and not detailed:
            return data_block
        if final_text and (detailed or len(final_text) > 60):
            return data_block + "\n\n" + final_text
        return data_block

    # Successful mutation or other non-read tool — trust the model text.
    return final_text or "error: no answer was produced for this turn"


def _latest_assistant_text(agent) -> str:
    """Walk backward through the full message history and return the last
    non-empty assistant text.  Only used for the legacy (non-orchestrated)
    code path — never as a fallback inside an orchestrated turn.
    """
    for message in reversed(agent.messages):
        if message.get("role") == "assistant":
            content = str(message.get("content") or "").strip()
            if content:
                return content
    return ""


async def _run_turn_agent(agent, settings, text: str) -> None:
    """Run one agent turn with timing, formatting, and error handling."""
    started = time.monotonic()
    detailed = wants_detailed_report(text)
    local_reply = _friendly_reply(text)
    if local_reply is not None:
        print()
        logo.ctrl("answer")
        print(local_reply)
        logo.ctrl("ready", f"{time.monotonic() - started:.1f}s")
        return

    try:
        await agent.run_turn(text)
        turn_result = getattr(agent, "last_turn_result", None)
        turn_state = getattr(getattr(turn_result, "state", None), "value", None)
        if turn_result is None or turn_state == "idle":
            final_text = _format_final_answer(
                agent,
                turn_result,
                show_thinking=settings.show_thinking,
                detailed=detailed,
            )
            if final_text:
                print()
                logo.ctrl("answer")
                print(final_text)
    except AuthenticationError:
        print(logo.paint("Authentication failed: the API key is missing or invalid.", logo.TEAL))
        print("Load your environment file before starting the agent.")
    except Exception as exc:
        print(f"error: {exc}")
    finally:
        logo.ctrl("ready", f"{time.monotonic() - started:.1f}s")


async def cli_main(settings: Settings) -> None:
    logo.print_banner()

    ui = CliUI(show_thinking=settings.show_thinking)
    store = SessionStore(settings.state_dir / "sessions.db")
    try:
        agent = build_agent(settings, ui, store=store)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    logo.ctrl("ready", f"{settings.workspace.resolve()}  security={settings.security_mode}")
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

        if text in {"/fast", "/smart", "/auto"}:
            val = text[1:] if text != "/auto" else None
            agent.router.forced = val
            logo.ctrl("router", f"forced to {val or 'auto'}")
            continue

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

        if text == "/dissect" or text.startswith("/dissect "):
            query = text[len("/dissect"):].strip()
            if not query:
                print("usage: /dissect <query> — run one turn with dissection (read-only) mode")
                continue
            settings.dissection_mode = True
            try:
                await _run_turn_agent(agent, settings, query)
            finally:
                settings.dissection_mode = False
            continue

        await _run_turn_agent(agent, settings, text)

    await agent.close()
