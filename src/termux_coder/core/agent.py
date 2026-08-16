from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from ..context.repomap import RepoMap
from ..context import (
    BudgetManager,
    ContextAssembler,
    ContextItem,
    PriorityEngine,
    TokenEstimator,
)
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
    lsp: object


class Agent:
    def __init__(self, settings, provider, registry: ToolRegistry, ui, store=None, resume_id=None) -> None:
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
        
        from ..lsp.manager import LspManager
        self.lsp = LspManager(
            self.jail, ui, enabled=settings.lsp_enabled, wait=settings.lsp_wait
        )

        # v0.6: Context Budget Manager
        self.estimator = TokenEstimator()
        # افتراضي: 8192 tokens، 2000 احتياطي للمخرجات
        self.budget = BudgetManager(
            max_tokens=8192,
            output_reserve=2000,
            estimator=self.estimator,
        )
        self.assembler = ContextAssembler(self.estimator, self.budget)

        self.store = store
        self.session_id = None
        self.resumed = False
        self._seq = 0
        
        self.messages: list[dict] = [
            {
                "role": "system",
                "content": build_system_prompt(str(self.jail.root), settings.security_mode),
            }
        ]

        if store is not None:
            info = store.get(resume_id) if resume_id else None
            if info and info["workspace"] == str(self.jail.root):
                self.session_id = info["id"]
                loaded = store.load_messages(self.session_id)
                if loaded:
                    self.messages.extend(loaded)
                    self._seq = len(loaded)
                st = store.load_state(self.session_id)
                if st is not None:
                    self.state = st
                self.resumed = bool(loaded)
            else:
                self.session_id = store.create(str(self.jail.root), settings.model)

        self.ctx = ToolContext(
            self.jail, settings, self.state, ui, self.audit, self.policy, self.repomap, self.lsp
        )

    async def close(self) -> None:
        if self.lsp is not None:
            await self.lsp.shutdown()
        if self.store:
            self.store.close()

    def _persist(self, message: dict) -> None:
        if not self.store or not self.session_id:
            return
        self.store.save_message(self.session_id, self._seq, message)
        self._seq += 1
        self.store.touch(self.session_id)

    def _refresh_map_message(self, map_text: str) -> None:
        content = "# Repository Map (auto-generated)\n" + map_text
        for m in self.messages:
            if m.get("role") == "system" and m.get("content", "").startswith("# Repository Map"):
                m["content"] = content
                return
        self.messages.insert(1, {"role": "system", "content": content})

    async def run_turn(self, user_text: str) -> None:
        user_message = {"role": "user", "content": user_text}
        self.messages.append(user_message)
        self._persist(user_message)
        if self.store and self._seq == 1:
            self.store.set_title(self.session_id, user_text[:40])

        await self.ui.on_event("turn_start")

        if self.settings.repo_map_enabled:
            map_text = await asyncio.to_thread(self.repomap.render_budget)
            if self.repomap.changed or not self._map_sent:
                await self.ui.on_event("map_ready", **self.repomap.last_stats)
                self._map_sent = True
            self._refresh_map_message(map_text)

        try:
            for _ in range(self.settings.max_tool_rounds):
                # v0.6: تحويل self.messages إلى ContextItems
                current_seq = len(self.messages) - 1
                items = [
                    PriorityEngine.classify(msg, i, current_seq)
                    for i, msg in enumerate(self.messages)
                ]

                # v0.6: تجميع السياق المضغوط
                assembled = self.assembler.assemble(items)
                stats = self.assembler.stats(items)

                # v0.6: إرسال stats للواجهة
                await self.ui.on_event("context_stats", **stats)

                with self.ui.thinking():
                    assistant = await self.provider.chat_stream(
                        assembled,  # استخدام assembled بدلاً من self.messages
                        self.registry.schemas(),
                        self.ui.on_token,
                    )
                await self.ui.on_event("assistant_done")
                self.messages.append(assistant)
                self._persist(assistant)

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
                    tool_msg = {"role": "tool", "tool_call_id": call["id"], "content": result}
                    self.messages.append(tool_msg)
                    self._persist(tool_msg)

            await self.ui.on_event("max_rounds")
        finally:
            if self.store and self.session_id:
                self.store.save_state(self.session_id, self.state)
            await self.ui.on_event("turn_end")
