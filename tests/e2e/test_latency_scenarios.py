"""Integration tests for bounded long-turn latency and slow tool detection."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from termux_coder.core.orchestrator import AgentOrchestrator, TurnState
from termux_coder.providers.mock import MockResponse
from termux_coder.tools import fs


class DelayedProvider:
    """Deterministic provider delay; no network or external API involved."""

    def __init__(self, responses: list[dict], delay_s: float) -> None:
        self.responses = list(responses)
        self.delay_s = delay_s
        self.calls = 0

    async def chat_stream(self, messages, tools, on_token):
        self.calls += 1
        await asyncio.sleep(self.delay_s)
        if self.responses:
            return self.responses.pop(0)
        return {"role": "assistant", "content": ""}


def run(coro):
    return asyncio.run(coro)


def _response_dict(response: MockResponse) -> dict:
    result = {"role": "assistant", "content": response.content}
    if response.tool_calls:
        result["tool_calls"] = response.tool_calls
    return result


def _build_latency_orchestrator(components, provider: DelayedProvider, handler: Callable):
    registry = components["registry"]
    registry.register("list_dir", "List workspace files", fs.ListDirArgs, handler)
    return AgentOrchestrator(
        provider=provider,
        registry=registry,
        policy_engine=components["policy_engine"],
        audit=components["audit"],
        ctx=components["ctx"],
        max_rounds=10,
        max_duration_s=10,
        on_event=components["ui"].on_event,
        approval_handler=components["ui"].request_approval,
        preview_service=None,
        verification_runner=None,
    )


def test_long_turn_records_round_count_and_per_tool_duration(e2e_components) -> None:
    async def delayed_list(args, ctx):
        await asyncio.sleep(0.025)
        return await fs.list_dir(args, ctx)

    provider = DelayedProvider(
        [
            _response_dict(MockResponse.with_tool("r1", "list_dir", {"path": "."})),
            _response_dict(MockResponse.with_tool("r2", "list_dir", {"path": "."})),
            _response_dict(MockResponse.text("Completed the read-only inspection.")),
        ],
        delay_s=0.025,
    )
    orchestrator = _build_latency_orchestrator(e2e_components, provider, delayed_list)

    started = time.monotonic()
    result = run(orchestrator.run_turn([{"role": "user", "content": "inspect slowly"}]))
    elapsed_s = time.monotonic() - started

    assert result.state is TurnState.IDLE
    assert result.rounds_used == 3
    assert provider.calls == 3
    assert elapsed_s >= 0.12
    assert len(result.tool_results) == 2
    assert all(item.ok for item in result.tool_results)
    assert all(item.duration_ms >= 15 for item in result.tool_results)
    round_events = [kind for kind, _ in e2e_components["ui"].events if kind == "round_start"]
    tool_events = [payload for kind, payload in e2e_components["ui"].events if kind == "tool_result"]
    assert len(round_events) == 3
    assert len(tool_events) == 2
    assert all(int(event["duration_ms"]) >= 15 for event in tool_events)


def test_long_turn_stops_at_wall_clock_deadline(e2e_components) -> None:
    responses = [
        _response_dict(MockResponse.with_tool(f"r{i}", "list_dir", {"path": "."}))
        for i in range(1, 8)
    ]
    provider = DelayedProvider(responses, delay_s=0.03)

    async def fast_list(args, ctx):
        return await fs.list_dir(args, ctx)

    orchestrator = _build_latency_orchestrator(e2e_components, provider, fast_list)
    orchestrator.max_duration_s = 0.08

    started = time.monotonic()
    result = run(orchestrator.run_turn([{"role": "user", "content": "inspect until timeout"}]))
    elapsed_s = time.monotonic() - started

    assert result.state is TurnState.FAILED
    assert result.error == "turn exceeded 0.08s limit"
    # The deadline check occurs at the start of the next counted round.
    assert result.rounds_used <= 4
    assert elapsed_s < 0.25
    assert provider.calls <= 3
    audit_events = e2e_components["audit"].tail(30)
    assert any(event.get("event") == "turn_start" for event in audit_events)


def test_slow_provider_is_distinguished_from_slow_tool(e2e_components) -> None:
    provider = DelayedProvider(
        [
            _response_dict(MockResponse.with_tool("r1", "list_dir", {"path": "."})),
            _response_dict(MockResponse.text("done")),
        ],
        delay_s=0.04,
    )

    async def fast_list(args, ctx):
        return await fs.list_dir(args, ctx)

    orchestrator = _build_latency_orchestrator(e2e_components, provider, fast_list)
    started = time.monotonic()
    result = run(orchestrator.run_turn([{"role": "user", "content": "measure latency"}]))
    elapsed_s = time.monotonic() - started

    assert result.state is TurnState.IDLE
    assert result.rounds_used == 2
    assert provider.calls == 2
    assert elapsed_s >= 0.07
    assert result.tool_results[0].duration_ms < 25
    assert elapsed_s > result.tool_results[0].duration_ms / 1000
