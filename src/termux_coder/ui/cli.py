from __future__ import annotations

import asyncio

from .. import logo
from .base import AgentUI


class CliUI(AgentUI):
    def thinking(self):
        return logo.Thinking()

    async def on_token(self, text: str) -> None:
        print(text, end="", flush=True)

    async def on_event(self, kind: str, **payload) -> None:
        if kind == "turn_start":
            print()
        elif kind == "assistant_done":
            print()
        elif kind in ("tool_recovered", "patch_recovered"):
            logo.ctrl("recovered", "tool call extracted from text")
        elif kind == "map_ready":
            logo.ctrl("map", f"{payload.get('files')} files · {payload.get('symbols')} symbols")
        elif kind == "model_route":
            logo.ctrl(
                f"route:{payload.get('tier')}",
                f"{payload.get('model', '')} · {payload.get('reason', '')}",
            )
        elif kind == "git_info":
            logo.ctrl(f"git:{payload.get('label')}", payload.get("detail", ""))
        elif kind == "lsp_on":
            logo.ctrl("lsp", payload.get("server", ""))
        elif kind == "lsp_off":
            logo.ctrl("lsp off", payload.get("reason", ""))
        elif kind == "lsp_diag":
            logo.ctrl(f"lsp:{payload.get('path')}", f"{payload.get('count')} problems")
        elif kind == "context_stats":
            total = payload.get("total_tokens", 0)
            budget = payload.get("budget", 1)
            pct = payload.get("usage_pct", 0)
            logo.ctrl("context", f"{pct:.0f}% · {total/1000:.1f}k / {budget/1000:.1f}k")
        elif kind == "tool_start":
            print()
            logo.ctrl(f"tool:{payload.get('name')}", str(payload.get("args"))[:120])
        elif kind == "tool_result":
            print(str(payload.get("text"))[:1500])
        elif kind == "verification_start":
            logo.ctrl("verify", "running project verification")
        elif kind == "verification_result":
            logo.ctrl(
                f"verify:{payload.get('status')}",
                f"exit={payload.get('exit_code')} · {payload.get('duration_ms')}ms",
            )
        elif kind == "tool_denied":
            logo.ctrl("denied", f"{payload.get('tool')}: {payload.get('reason', '')}")
        elif kind == "approval_requested":
            logo.ctrl("approval", f"{len(payload.get('calls', []))} operation(s) pending")
        elif kind == "orchestrator_result":
            logo.ctrl("orchestrator", f"{payload.get('state')}: {payload.get('error', '')}")
        elif kind == "max_rounds":
            print("stopped: too many tool rounds")

    async def request_approval(self, kind: str, payload: dict) -> bool:
        print()
        if kind == "patch":
            print(logo.paint(f"── proposed patch: {payload.get('path')} ──", logo.TEAL))
            print(payload.get("diff", ""))
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
        else:
            logo.ctrl("request command", payload.get("command", ""))
        loop = asyncio.get_running_loop()
        answer = await loop.run_in_executor(
            None, input, logo.paint("Apply? [y/N] ", logo.TEALB)
        )
        return answer.strip().lower() == "y"
