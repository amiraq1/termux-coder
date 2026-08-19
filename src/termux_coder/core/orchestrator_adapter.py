from __future__ import annotations

import asyncio
import time
from typing import Any

from ..providers.router import FAST_EXCLUDE
from .provider_health import ProviderHealth, classify_provider_error, health_payload


class RouterProviderAdapter:
    """Adapter يجعل ModelRouter مزودًا واحدًا متوافقًا مع AgentOrchestrator."""

    def __init__(self, router: Any, ui: Any, user_text: str) -> None:
        self.router = router
        self.ui = ui
        self.user_text = user_text
        self.round_idx = 0
        self.provider_health = ProviderHealth()

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
        self.provider_health.mark_checking()
        await self.ui.on_event(
            "provider_health",
            **health_payload(
                self.provider_health,
                provider=self.router.label_for(tier),
                model=self.router.label_for(tier),
            ),
        )
        started = time.monotonic()
        try:
            with self.ui.thinking():
                response = await provider.chat_stream(messages, schemas, on_token)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            latency_ms = (time.monotonic() - started) * 1000
            self.provider_health.mark_failure(classify_provider_error(exc), latency_ms)
            await self.ui.on_event(
                "provider_health",
                **health_payload(
                    self.provider_health,
                    provider=self.router.label_for(tier),
                    model=self.router.label_for(tier),
                ),
            )
            raise
        latency_ms = (time.monotonic() - started) * 1000
        if not response or (not response.get("content") and not response.get("tool_calls")):
            self.provider_health.mark_failure("empty_response", latency_ms)
        else:
            self.provider_health.mark_online(latency_ms)
        await self.ui.on_event(
            "provider_health",
            **health_payload(
                self.provider_health,
                provider=self.router.label_for(tier),
                model=self.router.label_for(tier),
            ),
        )
        return response

    def note_edit(self, tool_name: str) -> None:
        self.router.note_edit(tool_name)
