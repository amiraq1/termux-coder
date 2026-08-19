from __future__ import annotations

import asyncio
from pathlib import Path

from termux_coder.core.impact import ImpactAnalyzer
from termux_coder.core.orchestrator import AgentOrchestrator, TurnState
from termux_coder.core.registry import ToolRegistry
from termux_coder.providers.mock import MockProvider, MockResponse
from termux_coder.security.policy import PolicyEngine


class Audit:
    def __init__(self):
        self.events = []

    def log(self, event: str, **data):
        self.events.append({"event": event, **data})

    def has(self, event: str) -> bool:
        return any(item["event"] == event for item in self.events)


class Settings:
    max_output_chars = 8000
    analyzing_enabled = True
    research_auto_enabled = False


class Ctx:
    settings = Settings()


def build(root: Path, responses: list[MockResponse]):
    audit = Audit()
    provider = MockProvider(responses)
    events = []

    async def on_event(kind: str, **data):
        events.append((kind, data))

    orchestrator = AgentOrchestrator(
        provider=provider,
        registry=ToolRegistry(),
        policy_engine=PolicyEngine("AUTO"),
        audit=audit,
        ctx=Ctx(),
        max_rounds=2,
        max_duration_s=10,
        on_event=on_event,
        impact_analyzer=ImpactAnalyzer(root),
    )
    return orchestrator, audit, provider, events


def test_public_request_skips_analyzing_and_tools(tmp_path: Path):
    orchestrator, audit, provider, events = build(tmp_path, [MockResponse.text("2")])

    result = asyncio.run(
        orchestrator.run_turn([{"role": "user", "content": "what is 1+1"}])
    )

    assert result.state == TurnState.IDLE
    assert result.final_text == "2"
    assert provider.calls
    assert audit.has("impact_analysis_skipped")
    assert not audit.has("impact_analysis")
    assert not any(kind == "impact_analysis" for kind, _ in events)


def test_explicit_target_records_analysis_before_provider(tmp_path: Path):
    (tmp_path / "target.py").write_text("def greet():\n    return 'ok'\n", encoding="utf-8")
    (tmp_path / "caller.py").write_text(
        "from target import greet\n\ndef run():\n    return greet()\n",
        encoding="utf-8",
    )
    orchestrator, audit, provider, events = build(tmp_path, [MockResponse.text("done")])

    result = asyncio.run(
        orchestrator.run_turn(
            [{"role": "user", "content": "review function greet in target.py"}]
        )
    )

    assert result.state == TurnState.IDLE
    assert provider.calls
    analysis = next(item for item in audit.events if item["event"] == "impact_analysis")
    assert any(ref["path"] == "caller.py" for ref in analysis["confirmed_callers"])
    assert [kind for kind, _ in events].index("impact_analysis") < len(events)
    transitions = [
        (item.get("from_state"), item.get("to_state"))
        for item in audit.events
        if item["event"] == "state_transition"
    ]
    assert ("planning", "analyzing") in transitions
    assert ("analyzing", "planning") in transitions


def test_dynamic_scope_halts_before_provider_and_is_audited(tmp_path: Path):
    (tmp_path / "target.py").write_text("def greet():\n    return 'ok'\n", encoding="utf-8")
    (tmp_path / "plugin.py").write_text(
        "import importlib\nmodule = importlib.import_module('target')\ngetattr(module, 'greet')()\n",
        encoding="utf-8",
    )
    orchestrator, audit, provider, events = build(tmp_path, [MockResponse.text("must not run")])

    result = asyncio.run(
        orchestrator.run_turn(
            [{"role": "user", "content": "modify function greet in target.py"}]
        )
    )

    assert result.state == TurnState.IDLE
    assert result.error and "dynamic references" in result.error
    assert provider.calls == []
    assert audit.has("impact_analysis")
    assert audit.has("halt")
    assert any(kind == "halt" for kind, _ in events)
    transitions = [
        (item.get("from_state"), item.get("to_state"))
        for item in audit.events
        if item["event"] == "state_transition"
    ]
    assert ("analyzing", "idle") in transitions
