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
from ..providers.router import FAST_EXCLUDE
from .recovery import recover_tool_calls
from ..security.audit import AuditLog
from ..security.jail import WorkspaceJail
from ..security.policy import CommandPolicy, PolicyEngine
from .context import SessionState, build_system_prompt
from .registry import ToolRegistry
from .orchestrator import AgentOrchestrator, TurnState
from .orchestrator_adapter import RouterProviderAdapter
from .verification import VerificationRunner
from .research import ResearchCoordinator
from ..tools.preview import PatchPreviewService
from ..tools.duckduckgo import DuckDuckGoProvider
from ..tools.fetch_page import FetchPageService


@dataclass
class ToolContext:
    jail: WorkspaceJail
    settings: object
    state: SessionState
    ui: object
    audit: AuditLog
    policy: CommandPolicy
    policy_engine: PolicyEngine
    repomap: object
    lsp: object
    research_coordinator: ResearchCoordinator | None = None


class Agent:
    def __init__(self, settings, router, registry: ToolRegistry, ui, store=None, resume_id=None) -> None:
        self.settings = settings
        self.router = router
        self.registry = registry
        self.ui = ui
        self.jail = WorkspaceJail(settings.workspace)
        self.state = SessionState()
        self.audit = AuditLog(settings.state_dir / "audit.jsonl")
        self.policy = CommandPolicy(settings.security_mode)
        self.policy_engine = PolicyEngine(settings.security_mode)
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

        self.research_coordinator = None
        if (
            getattr(settings, "web_search_enabled", True)
            and getattr(settings, "research_auto_enabled", True)
        ):
            search_provider = DuckDuckGoProvider(
                timeout_s=settings.web_search_timeout_s,
                max_response_bytes=settings.web_search_max_response_bytes,
                max_results=settings.web_search_max_results,
            )
            self.research_coordinator = ResearchCoordinator(
                search_provider,
                FetchPageService(
                    timeout_s=settings.web_search_timeout_s,
                    max_response_bytes=settings.web_search_max_response_bytes,
                ),
                max_sources=min(settings.web_search_max_results, 8),
            )
        self.ctx = ToolContext(
            self.jail,
            settings,
            self.state,
            ui,
            self.audit,
            self.policy,
            self.policy_engine,
            self.repomap,
            self.lsp,
            self.research_coordinator,
        )
        self.orchestrator: AgentOrchestrator | None = None

    async def _run_turn_orchestrated(self, user_text: str) -> None:
        """مسار P2 التجريبي؛ يحافظ على عقد الجلسة ويستخدم المسار القديم كخطة تراجع."""
        user_message = {"role": "user", "content": user_text}
        self.messages.append(user_message)
        self._persist(user_message)
        if self.store and self._seq == 1:
            self.store.set_title(self.session_id, user_text[:40])

        if self.settings.repo_map_enabled:
            map_text = await asyncio.to_thread(self.repomap.render_budget)
            if self.repomap.changed or not self._map_sent:
                await self.ui.on_event("map_ready", **self.repomap.last_stats)
                self._map_sent = True
            self._refresh_map_message(map_text)

        def prepare_messages(messages: list[dict]) -> list[dict]:
            current_seq = len(messages) - 1
            items = [
                PriorityEngine.classify(msg, i, current_seq)
                for i, msg in enumerate(messages)
            ]
            return self.assembler.assemble(items)

        provider = RouterProviderAdapter(self.router, self.ui, user_text)
        provider.begin_turn()
        self.orchestrator = AgentOrchestrator(
            provider=provider,
            registry=self.registry,
            policy_engine=self.policy_engine,
            audit=self.audit,
            ctx=self.ctx,
            max_rounds=self.settings.max_tool_rounds,
            max_duration_s=max(60.0, self.settings.command_timeout * 2.0),
            on_event=self.ui.on_event,
            approval_handler=self.ui.request_approval,
            message_sink=self._persist,
            message_preparer=prepare_messages,
            preview_service=PatchPreviewService(self.jail, self.state),
            verification_runner=(
                VerificationRunner(self.jail.root, self.settings)
                if self.settings.verification_enabled else None
            ),
        )
        try:
            result = await self.orchestrator.run_turn(
                self.messages,
                on_token=self.ui.on_token,
            )
            if result.state != TurnState.IDLE:
                await self.ui.on_event(
                    "orchestrator_result",
                    state=result.state.value,
                    error=result.error or "",
                )
        finally:
            # Always release the TUI busy state, including failure and cancellation.
            await self.ui.on_event("turn_end")

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
        if self.settings.orchestrator_enabled:
            await self._run_turn_orchestrated(user_text)
            return

        self.router.begin_turn()
        intent_edit = self.router.looks_like_edit(user_text)
        intent_run = self.router.looks_like_run(user_text)
        escalated = False

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
            for round_idx in range(self.settings.max_tool_rounds):
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

                tier, reason = self.router.tier_for_round(
                    round_idx, user_text, self.messages
                )
                provider = self.router.provider_for(tier)
                schemas = self.registry.schemas(
                    exclude=None if tier == "smart" else FAST_EXCLUDE
                )
                await self.ui.on_event(
                    "model_route", tier=tier, model=self.router.label_for(tier), reason=reason
                )

                with self.ui.thinking():
                    assistant = await provider.chat_stream(
                        assembled, schemas, self.ui.on_token
                    )
                await self.ui.on_event("assistant_done")

                tool_calls = assistant.get("tool_calls")
                if not tool_calls:
                    recovered = recover_tool_calls(
                        assistant.get("content") or "", self.registry
                    )
                    if recovered:
                        assistant["tool_calls"] = recovered
                        tool_calls = recovered
                        await self.ui.on_event("tool_recovered", count=len(recovered))

                # تصعيد مُسبَّب: نيّة تعديل/تنفيذ + fast بلا أدوات → جولة smart واحدة
                if (
                    not tool_calls
                    and tier == "fast"
                    and not escalated
                    and self.router.forced != "fast"
                    and (intent_edit or intent_run)
                ):
                    escalated = True
                    if intent_edit:
                        self.router.edit_mode = True
                    await self.ui.on_event(
                        "model_route",
                        tier="smart",
                        model=self.router.label_for("smart"),
                        escalated=True,
                        reason=(
                            "edit_intent_without_tool"
                            if intent_edit
                            else "run_intent_without_tool"
                        ),
                    )
                    with self.ui.thinking():
                        assistant = await self.router.smart.chat_stream(
                            assembled, self.registry.schemas(), self.ui.on_token
                        )
                    await self.ui.on_event("assistant_done")
                    tool_calls = assistant.get("tool_calls")
                    if not tool_calls:
                        recovered = recover_tool_calls(
                            assistant.get("content") or "", self.registry
                        )
                        if recovered:
                            assistant["tool_calls"] = recovered
                            tool_calls = recovered
                            await self.ui.on_event("tool_recovered", count=len(recovered))

                self.messages.append(assistant)
                self._persist(assistant)

                if not tool_calls:
                    return

                for call in (tool_calls or []):
                    self.router.note_edit(call["function"]["name"])

                for call in tool_calls:
                    name = call["function"]["name"]
                    await self.ui.on_event("tool_start", name=name, args=call["function"]["arguments"])

                    handler = self.registry.handler(name)
                    if handler is None:
                        result = f"unknown tool: {name}"
                    else:
                        # فحص صلاحية الأداة من PolicyEngine، لا من مخرجات النموذج
                        decision = self.policy_engine.evaluate_tool(name)
                        if not decision.allowed:
                            result = f"tool blocked by policy: {decision.reason}"
                            self.audit.log(
                                "tool_blocked",
                                tool=name,
                                reason=decision.reason,
                                mode=self.policy_engine.mode,
                            )
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
