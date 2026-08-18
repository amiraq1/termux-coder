from __future__ import annotations

import asyncio

from termux_coder.core.orchestrator_adapter import RouterProviderAdapter
class FakeRouter:
    def __init__(self, provider):
        self.fast = provider
        self.smart = provider
        self.forced = None
        self.edit_mode = False

    def begin_turn(self):
        self.edit_mode = False

    def tier_for_round(self, round_idx, user_text, messages):
        return ("fast", "test") if round_idx == 0 else ("smart", "follow_up")

    def provider_for(self, tier):
        return self.fast if tier == "fast" else self.smart

    def label_for(self, tier):
        return tier

    def note_edit(self, tool_name):
        self.edit_mode = True


class FakeUI:
    def thinking(self):
        from contextlib import nullcontext
        return nullcontext()

    async def on_event(self, *_args, **_kwargs):
        pass


# مزود بسيط يعيد dict للتحقق من عقد Adapter.
class DictProvider:
    def __init__(self):
        self.calls = []

    async def chat_stream(self, messages, tools, on_token):
        self.calls.append({"messages": messages, "tools": tools})
        return {"role": "assistant", "content": "ok"}


def test_router_adapter_filters_mutating_tools_for_fast_tier():
    async def run():
        provider = DictProvider()
        router = FakeRouter(provider)
        adapter = RouterProviderAdapter(router, FakeUI(), "inspect files")
        adapter.begin_turn()
        tools = [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "apply_patch"}},
        ]
        result = await adapter.chat_stream([], tools, lambda _token: None)
        assert result["content"] == "ok"
        sent = provider.calls[0]["tools"]
        assert [x["function"]["name"] for x in sent] == ["read_file"]

    asyncio.run(run())


def test_router_adapter_switches_tier_between_rounds():
    async def run():
        provider = DictProvider()
        router = FakeRouter(provider)
        adapter = RouterProviderAdapter(router, FakeUI(), "inspect files")
        adapter.begin_turn()
        await adapter.chat_stream([], [], lambda _token: None)
        await adapter.chat_stream([], [], lambda _token: None)
        assert len(provider.calls) == 2

    asyncio.run(run())
