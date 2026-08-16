from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from ..context.repomap import RepoMap
from ..security.audit import AuditLog
from ..security.jail import WorkspaceJail
from ..security.policy import CommandPolicy
from .context import SessionState, build_system_prompt
from .registry import ToolRegistry


@dataclass
class ToolContext:
    jail: WorkspaceJail
    settings: object
    state: SessionState
    ui: object
    audit: AuditLog
    policy: CommandPolicy
    repomap: object


class Agent:
    def __init__(self, settings, provider, registry: ToolRegistry, ui) -> None:
        self.settings = settings
        self.provider = provider
        self.registry = registry
        self.ui = ui
        self.jail = WorkspaceJail(settings.workspace)
        self.state = SessionState()
        self.audit = AuditLog(settings.state_dir / "audit.jsonl")
        self.policy = CommandPolicy(settings.security_mode)
        self.repomap = RepoMap(self.jail, settings.repo_map_budget)
        self._map_sent = False
        self.ctx = ToolContext(
            self.jail, settings, self.state, ui, self.audit, self.policy, self.repomap
        )
        self.messages: list[dict] = [
            {
                "role": "system",
                "content": build_system_prompt(str(self.jail.root), settings.security_mode),
            }
        ]

    def _refresh_map_message(self, map_text: str) -> None:
        content = "# Repository Map (auto-generated)\n" + map_text
        for m in self.messages:
            if m.get("role") == "system" and m.get("content", "").startswith("# Repository Map"):
                m["content"] = content
                return
        self.messages.insert(1, {"role": "system", "content": content})

    async def run_turn(self, user_text: str) -> None:
        self.messages.append({"role": "user", "content": user_text})
        await self.ui.on_event("turn_start")

        if self.settings.repo_map_enabled:
            map_text = await asyncio.to_thread(self.repomap.render_budget)
            if self.repomap.changed or not self._map_sent:
                await self.ui.on_event("map_ready", **self.repomap.last_stats)
                self._map_sent = True
            self._refresh_map_message(map_text)

        try:
            for _ in range(self.settings.max_tool_rounds):
                with self.ui.thinking():
                    assistant = await self.provider.chat_stream(
                        self.messages, self.registry.schemas(), self.ui.on_token
                    )
                await self.ui.on_event("assistant_done")
                self.messages.append(assistant)

                tool_calls = assistant.get("tool_calls")
                if not tool_calls:
                    return

                for call in tool_calls:
                    name = call["function"]["name"]
                    await self.ui.on_event("tool_start", name=name, args=call["function"]["arguments"])

                    handler = self.registry.handler(name)
                    if handler is None:
                        result = f"unknown tool: {name}"
                    else:
                        try:
                            args = json.loads(call["function"]["arguments"] or "{}")
                        except Exception as exc:
                            result = f"invalid arguments: {exc}"
                        else:
                            try:
                                result = await handler(args, self.ctx)
                            except Exception as exc:
                                result = f"tool error: {exc}"

                    await self.ui.on_event("tool_result", name=name, text=result)
                    self.messages.append(
                        {"role": "tool", "tool_call_id": call["id"], "content": result}
                    )

            await self.ui.on_event("max_rounds")
        finally:
            await self.ui.on_event("turn_end")
