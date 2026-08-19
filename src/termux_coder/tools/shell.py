from __future__ import annotations

import asyncio
import shlex
import subprocess
from pydantic import BaseModel, ConfigDict

from ..security.scrubber import scrub

class RunCommandArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str



async def run_command(args: RunCommandArgs, ctx) -> str:
    command = (args.command or "").strip()
    if not command:
        return "empty command"
        
    # منع pytest إذا لم يكن هناك ملفات اختبار
    if "pytest" in command and not any(f.endswith("_test.py") or f.endswith("test_*.py") for f in ctx.state.read_files):
        ctx.audit.log("command_blocked", command=command, reason="no_test_files")
        return "skipped: no test files found"

    if not ctx.policy.command_allowed_at_all():
        return "run_command disabled (security=READONLY)"

    auto_verification = (
        getattr(ctx.policy, "mode", "ASK") == "GRANULAR"
        and ctx.policy.is_auto_verification(command)
    )

    if ctx.policy.is_blocked(command):
        ctx.audit.log("command_blocked", command=command)
        return "command blocked by policy"

    if getattr(ctx.policy, "mode", "ASK") == "AUTO" and not ctx.policy.is_auto_allowlisted(command):
        ctx.audit.log("command_blocked", command=command, reason="auto_allowlist")
        return "command blocked by AUTO allowlist"

    if ctx.policy.requires_approval(command) and not getattr(ctx, "orchestrator_approval_granted", False):
        approved = await ctx.ui.request_approval(
            "command",
            {
                "command": command,
                "risk": "low" if auto_verification else "high",
            },
        )
        ctx.audit.log("command_approval", command=command, approved=approved, source="tool")
        if not approved:
            return "user rejected the command"
    elif ctx.policy.requires_approval(command):
        ctx.audit.log("command_approval", command=command, approved=True, source="orchestrator")

    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        return f"invalid command syntax: {exc}"
    if not argv:
        return "empty command"

    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            argv,
            shell=False,
            cwd=ctx.jail.root,
            capture_output=True,
            text=True,
            timeout=ctx.settings.command_timeout,
        )
    except subprocess.TimeoutExpired:
        return f"timeout after {ctx.settings.command_timeout}s"

    ctx.audit.log("command_exec", command=command, exit=proc.returncode)
    out = f"exit={proc.returncode}\n"
    if proc.stdout:
        out += proc.stdout
    if proc.stderr:
        out += proc.stderr

    # Treat command output as untrusted data.  Scrub both the echoed command
    # and stdout/stderr before either crosses the UI or model boundary.
    safe_command = scrub(command)
    safe_output = scrub(out)
    await ctx.ui.on_event("shell_done", command=safe_command, output=safe_output)
    return safe_output[: ctx.settings.max_output_chars]
