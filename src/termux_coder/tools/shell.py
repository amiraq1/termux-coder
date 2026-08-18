from __future__ import annotations

import asyncio
import subprocess
from pydantic import BaseModel, ConfigDict

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

    if ctx.policy.is_blocked(command):
        ctx.audit.log("command_blocked", command=command)
        return "command blocked by policy"

    if ctx.policy.requires_approval(command):
        approved = await ctx.ui.request_approval("command", {"command": command})
        ctx.audit.log("command_approval", command=command, approved=approved)
        if not approved:
            return "user rejected the command"

    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            command,
            shell=True,
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
    await ctx.ui.on_event("shell_done", command=command, output=out)
    return out[: ctx.settings.max_output_chars]
