from __future__ import annotations

import asyncio
from contextlib import nullcontext
from typing import Any

from .. import logo
from .base import AgentUI


class CliUI(AgentUI):
    """Compact terminal UI designed for narrow Termux screens.

    Model tokens and internal reasoning are deliberately kept off-screen.
    The CLI shows only durable status updates, approvals, and the final answer.
    """

    def __init__(self, *, show_thinking: bool = False) -> None:
        self.show_thinking = show_thinking
        self._token_buffer: list[str] = []

    def thinking(self):
        # The optional spinner is only a compact progress indicator. Raw
        # reasoning and streamed tool-call text are never printed.
        return logo.Thinking() if self.show_thinking else nullcontext()

    async def on_token(self, text: str) -> None:
        # Keep streamed content available for diagnostics without printing
        # intermediate model text that may be a tool-call preamble.
        if text:
            self._token_buffer.append(text)

    async def on_event(self, kind: str, **payload: Any) -> None:
        if kind == "turn_start":
            self._token_buffer.clear()
            logo.ctrl("working")
            return
        if kind in ("assistant_done", "turn_end"):
            return
        # The dissection coverage summary is a result, not routine progress —
        # it stays visible even in quiet mode so partial coverage never hides.
        if kind == "exploration_update":
            event = payload.get("event") or {}
            summary = event.get("summary")
            if summary:
                print(summary.rstrip())
                return
            if not self.show_thinking:
                return
        # In quiet mode, routine progress stays hidden, but safety and
        # failure outcomes remain visible so a failed change never disappears.
        if not self.show_thinking:
            if kind == "verification_result":
                status = str(payload.get("status") or "unknown")
                if status not in {"passed", "skipped", "ok"}:
                    logo.ctrl("verify", status)
            elif kind == "patch_plan_rollback":
                errors = payload.get("errors") or []
                logo.ctrl("rollback", "failed" if errors else "completed")
            elif kind == "tool_denied":
                reason = str(payload.get("reason") or "denied by policy")
                logo.ctrl("denied", reason)
            elif kind == "tool_suppressed":
                tool = str(payload.get("tool") or "operation")
                reason = str(payload.get("reason") or "not relevant to this request")
                logo.ctrl("tool skipped", f"{tool}: {reason}")
            elif kind == "orchestrator_result":
                state = str(payload.get("state") or "failed")
                error = str(payload.get("error") or "")
                logo.ctrl("error", error or state)
            elif kind == "max_rounds":
                logo.ctrl("stopped", "maximum tool rounds reached")
            return
        if kind in ("tool_recovered", "patch_recovered"):
            logo.ctrl("recovered", "tool call normalized")
        elif kind == "map_ready":
            files = payload.get("files", 0)
            symbols = payload.get("symbols", 0)
            if files or symbols:
                logo.ctrl("map", f"{files} files · {symbols} symbols")
        elif kind == "model_route":
            tier = payload.get("tier") or "auto"
            reason = payload.get("reason") or ""
            detail = tier if not reason else f"{tier} · {reason}"
            logo.ctrl("route", detail)
        elif kind == "git_info":
            label = payload.get("label") or "status"
            logo.ctrl(f"git:{label}", payload.get("detail", ""))
        elif kind == "lsp_on":
            logo.ctrl("lsp", payload.get("server", ""))
        elif kind == "lsp_off":
            logo.ctrl("lsp off", payload.get("reason", ""))
        elif kind == "lsp_diag":
            logo.ctrl(f"lsp:{payload.get('path') or 'file'}", f"{payload.get('count', 0)} problems")
        elif kind == "tool_start":
            name = payload.get("name") or payload.get("tool") or "operation"
            logo.ctrl("tool", str(name))
        elif kind == "tool_result":
            name = payload.get("name") or payload.get("tool") or "operation"
            logo.ctrl("tool done", str(name))
        elif kind == "verification_start":
            logo.ctrl("verify", "running")
        elif kind == "verification_result":
            status = payload.get("status") or "unknown"
            duration = payload.get("duration_ms")
            detail = str(status)
            if duration is not None:
                detail += f" · {duration}ms"
            logo.ctrl("verify", detail)
        elif kind == "patch_plan_rollback":
            errors = payload.get("errors") or []
            logo.ctrl("rollback", "failed" if errors else "completed")
        elif kind == "tool_denied":
            tool = payload.get("tool") or "operation"
            logo.ctrl("denied", f"{tool}: {payload.get('reason', '')}")
        elif kind == "tool_suppressed":
            tool = payload.get("tool") or "operation"
            logo.ctrl("tool skipped", f"{tool}: {payload.get('reason', '')}")
        elif kind == "approval_requested":
            count = len(payload.get("calls", []))
            logo.ctrl("approval", f"{count} operation(s) pending")
        elif kind == "orchestrator_result":
            state = payload.get("state") or "failed"
            error = payload.get("error") or ""
            logo.ctrl("status", f"{state}: {error}" if error else state)
        elif kind == "max_rounds":
            logo.ctrl("stopped", "maximum tool rounds reached")

    async def request_approval(self, kind: str, payload: dict) -> bool:
        print()
        risk = str(payload.get("risk", "medium")).upper()
        print(f"Risk: {risk}")
        if kind == "patch":
            symbol = payload.get("symbol")
            label = f"{symbol} in " if symbol else ""
            print(logo.paint(f"── proposed {label}patch: {payload.get('path')} ──", logo.TEAL))
            print(payload.get("diff", "") or payload.get("replacement", ""))
        elif kind == "patch_plan":
            print(logo.paint(f"── proposed patch plan: {payload.get('plan_id')} ──", logo.TEAL))
            print(payload.get("summary", ""))
            print("Files: " + ", ".join(payload.get("paths", [])))
            print(payload.get("diff", ""))
        elif kind == "rollback_plan":
            print(logo.paint(f"── rollback patch plan: {payload.get('plan_id')} ──", logo.TEAL))
            print("Files: " + ", ".join(payload.get("paths", [])))
        elif kind == "network":
            print(logo.paint(f"── {payload.get('title', 'Approve network request?')} ──", logo.TEAL))
            print(f"Provider: {payload.get('provider', '')}")
            target = payload.get("query") or payload.get("url", "")
            print(f"Target: {target}")
            print("Results are untrusted web data.")
        elif kind == "git":
            print(logo.paint(f"── {payload.get('title')} ──", logo.TEAL))
            print(payload.get("body", ""))
        elif kind == "write_file":
            print(logo.paint(f"── {payload.get('title', 'Approve file write?')} ──", logo.TEAL))
            print(f"Path: {payload.get('path', '')}")
            action = "create" if payload.get("creates_file") else "overwrite"
            print(f"Action: {action}")
            print(f"Bytes: {payload.get('bytes', 0)}")
            if payload.get("old_sha256"):
                print(f"Old sha256: {payload['old_sha256'][:16]}…")
            if payload.get("new_sha256"):
                print(f"New sha256: {payload['new_sha256'][:16]}…")
        else:
            logo.ctrl("approval", payload.get("command", ""))
        loop = asyncio.get_running_loop()
        answer = await loop.run_in_executor(
            None, input, logo.paint("Apply? [y/N] ", logo.TEALB)
        )
        return answer.strip().lower() == "y"
