from __future__ import annotations

from typing import Any

from ..providers.router import FAST_EXCLUDE


class RouterProviderAdapter:
    """Adapter يجعل ModelRouter مزودًا واحدًا متوافقًا مع AgentOrchestrator."""

    def __init__(self, router: Any, ui: Any, user_text: str) -> None:
        self.router = router
        self.ui = ui
        self.user_text = user_text
        self.round_idx = 0

    def begin_turn(self) -> None:
        self.router.begin_turn()
        self.round_idx = 0

    async def chat_stream(self, messages: list[dict], tools: list[dict], on_token) -> dict:
        tier, reason = self.router.tier_for_round(
            self.round_idx, self.user_text, messages
        )
        self.round_idx += 1
        provider = self.router.provider_for(tier)
        schemas = tools
        if tier != "smart":
            schemas = [
                schema
                for schema in tools
                if schema.get("function", {}).get("name") not in FAST_EXCLUDE
            ]

        await self.ui.on_event(
            "model_route",
            tier=tier,
            model=self.router.label_for(tier),
            reason=reason,
        )
        with self.ui.thinking():
            return await provider.chat_stream(messages, schemas, on_token)

    def note_edit(self, tool_name: str) -> None:
        self.router.note_edit(tool_name)
