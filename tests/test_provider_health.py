from __future__ import annotations

import asyncio

import httpx
import pytest

from termux_coder.core.orchestrator_adapter import RouterProviderAdapter
from termux_coder.core.provider_health import (
    ProviderHealth,
    ProviderHealthState,
    classify_provider_error,
)


class Router:
    forced = None
    edit_mode = False

    def begin_turn(self):
        pass

    def tier_for_round(self, _round_idx, _user_text, _messages):
        return "fast", "test"

    def provider_for(self, _tier):
        return self.provider

    def label_for(self, tier):
        return tier


class UI:
    def __init__(self):
        self.events = []

    def thinking(self):
        from contextlib import nullcontext

        return nullcontext()

    async def on_event(self, kind, **payload):
        self.events.append((kind, payload))


class SuccessProvider:
    async def chat_stream(self, _messages, _tools, _on_token):
        return {"role": "assistant", "content": "ok"}


class TimeoutProvider:
    async def chat_stream(self, _messages, _tools, _on_token):
        raise httpx.ConnectTimeout("secret-api-key-must-not-leak")


def test_provider_health_marks_success_online_without_sensitive_data():
    async def run():
        router = Router()
        router.provider = SuccessProvider()
        ui = UI()
        adapter = RouterProviderAdapter(router, ui, "hello")
        adapter.begin_turn()
        result = await adapter.chat_stream([], [], lambda _token: None)
        assert result["content"] == "ok"
        health_events = [payload for kind, payload in ui.events if kind == "provider_health"]
        assert [event["state"] for event in health_events] == ["checking", "online"]
        assert health_events[-1]["latency_ms"] is not None
        assert all("secret-api-key" not in repr(event) for event in health_events)

    asyncio.run(run())


def test_provider_health_maps_network_failure_to_offline():
    async def run():
        router = Router()
        router.provider = TimeoutProvider()
        ui = UI()
        adapter = RouterProviderAdapter(router, ui, "hello")
        adapter.begin_turn()
        with pytest.raises(httpx.ConnectTimeout):
            await adapter.chat_stream([], [], lambda _token: None)
        health_events = [payload for kind, payload in ui.events if kind == "provider_health"]
        assert [event["state"] for event in health_events] == ["checking", "offline"]
        assert health_events[-1]["error_kind"] == "timeout"

    asyncio.run(run())


def test_provider_health_classifies_auth_and_rate_limit_errors():
    request = httpx.Request("POST", "https://provider.invalid/v1")
    assert classify_provider_error(
        httpx.HTTPStatusError("unauthorized", request=request, response=httpx.Response(401, request=request))
    ) == "auth"
    assert classify_provider_error(
        httpx.HTTPStatusError("limited", request=request, response=httpx.Response(429, request=request))
    ) == "rate_limited"


def test_provider_health_state_transitions_reset_failures_on_success():
    health = ProviderHealth()
    health.mark_checking()
    health.mark_failure("network", 10)
    assert health.state is ProviderHealthState.OFFLINE
    assert health.consecutive_failures == 1
    health.mark_online(5)
    assert health.state is ProviderHealthState.ONLINE
    assert health.consecutive_failures == 0
