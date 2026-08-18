from __future__ import annotations

import asyncio

from termux_coder.providers import openai_compat
from termux_coder.providers.router import ModelRouter


class EmptyStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class FakeCompletions:
    def __init__(self):
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return EmptyStream()


class FakeClient:
    def __init__(self):
        self.completions = FakeCompletions()
        self.chat = type("Chat", (), {"completions": self.completions})()


def test_openai_compat_disables_parallel_tool_calls_by_default(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(openai_compat, "AsyncOpenAI", lambda **_kwargs: client)
    monkeypatch.delenv("TERMUX_CODER_SINGLE_TOOL_CALLS", raising=False)
    provider = openai_compat.OpenAICompatProvider("key", "https://example.com", "model")

    asyncio.run(provider.chat_stream([], [{"function": {"name": "read_file"}}], lambda _: None))

    assert client.completions.kwargs["parallel_tool_calls"] is False


def test_openai_compat_can_allow_parallel_tool_calls_explicitly(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(openai_compat, "AsyncOpenAI", lambda **_kwargs: client)
    monkeypatch.setenv("TERMUX_CODER_SINGLE_TOOL_CALLS", "0")
    provider = openai_compat.OpenAICompatProvider("key", "https://example.com", "model")

    asyncio.run(provider.chat_stream([], [{"function": {"name": "read_file"}}], lambda _: None))

    assert "parallel_tool_calls" not in client.completions.kwargs


def test_router_stays_smart_after_symbol_patch():
    class FakeUI:
        pass

    router = ModelRouter(object(), object(), "fast", "smart", FakeUI())
    router.begin_turn()
    router.note_edit("apply_symbol_patch")

    tier, reason = router.tier_for_round(1, "run tests", [])

    assert tier == "smart"
    assert reason == "edit_mode"
