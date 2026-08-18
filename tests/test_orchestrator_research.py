from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from termux_coder.core.context import SessionState
from termux_coder.core.orchestrator import AgentOrchestrator, TurnState
from termux_coder.core.registry import ToolRegistry
from termux_coder.models.research import EvidenceItem, ResearchPacket
from termux_coder.providers.mock import MockProvider, MockResponse
from termux_coder.security.policy import PolicyEngine


class FakeAudit:
    def __init__(self):
        self.events = []

    def log(self, event, **payload):
        self.events.append({"event": event, **payload})


class Settings:
    research_auto_enabled = True
    max_output_chars = 4000


class FakeCoordinator:
    def __init__(self, packet=None, error=None):
        self.packet = packet
        self.error = error
        self.calls = []

    async def research(self, intent):
        self.calls.append(intent)
        if self.error:
            raise self.error
        return self.packet


def packet():
    item = EvidenceItem(
        source_url="https://docs.example.com/api",
        title="Official API",
        source_type="official_docs",
        excerpt="Use the current async API.",
        retrieved_at=datetime.now(timezone.utc),
        source_hash="a" * 64,
        version_compatible=True,
    )
    return ResearchPacket(
        intent_id="intent-1234",
        query="latest API",
        evidence=[item],
        selected_urls=[item.source_url],
        confidence="high",
    )


def build(coordinator, responses=None, mode="AUTO", approval_handler=None):
    events = []
    audit = FakeAudit()
    state = SessionState()
    ctx = type("Ctx", (), {})()
    ctx.settings = Settings()
    ctx.state = state
    ctx.research_coordinator = coordinator
    provider = MockProvider(responses or [MockResponse.text("done")])

    async def on_event(kind, **payload):
        events.append((kind, payload))

    orch = AgentOrchestrator(
        provider=provider,
        registry=ToolRegistry(),
        policy_engine=PolicyEngine(mode),
        audit=audit,
        ctx=ctx,
        max_rounds=3,
        max_duration_s=10,
        on_event=on_event,
        approval_handler=approval_handler,
    )
    return orch, ctx, provider, events, audit


def test_orchestrator_auto_researches_latest_docs_and_persists_packet():
    coordinator = FakeCoordinator(packet())
    orch, ctx, provider, events, audit = build(coordinator)
    messages = [{"role": "user", "content": "Use the latest API documentation"}]

    result = asyncio.run(orch.run_turn(messages))

    assert result.state == TurnState.IDLE
    assert len(coordinator.calls) == 1
    assert ctx.state.research_packet["packet_id"] == coordinator.packet.packet_id
    assert any(kind == "research_start" for kind, _ in events)
    assert any(kind == "research_packet" for kind, _ in events)
    assert any("<research_evidence>" in message.get("content", "") for message in messages)
    assert any(item["event"] == "research_packet_created" for item in audit.events)
    assert len(provider.calls) == 1


def test_orchestrator_skips_auto_research_for_local_task():
    coordinator = FakeCoordinator(packet())
    orch, _ctx, provider, events, _audit = build(coordinator)

    result = asyncio.run(
        orch.run_turn([{"role": "user", "content": "Rename this local variable"}])
    )

    assert result.state == TurnState.IDLE
    assert coordinator.calls == []
    assert not any(kind == "research_start" for kind, _ in events)
    assert len(provider.calls) == 1


def test_orchestrator_requires_network_approval_in_ask_mode():
    coordinator = FakeCoordinator(packet())
    approvals = []

    async def reject(kind, payload):
        approvals.append((kind, payload))
        return False

    orch, _ctx, provider, _events, _audit = build(
        coordinator,
        mode="ASK",
        approval_handler=reject,
    )

    result = asyncio.run(
        orch.run_turn([{"role": "user", "content": "Use the latest library docs"}])
    )

    assert result.state == TurnState.CANCELLED
    assert coordinator.calls == []
    assert provider.calls == []
    assert approvals[0][0] == "network"


def test_orchestrator_fails_closed_when_automatic_research_fails():
    coordinator = FakeCoordinator(error=RuntimeError("network unavailable"))
    orch, _ctx, provider, events, audit = build(coordinator)

    result = asyncio.run(
        orch.run_turn([{"role": "user", "content": "Use the latest library docs"}])
    )

    assert result.state == TurnState.FAILED
    assert "automatic research failed" in result.error
    assert provider.calls == []
    assert any(kind == "research_failed" for kind, _ in events)
    assert any(item["event"] == "research_automatic_failed" for item in audit.events)
