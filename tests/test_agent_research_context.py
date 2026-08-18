from types import SimpleNamespace

from termux_coder.core.agent import Agent
from termux_coder.core.orchestrator import AgentOrchestrator


def test_clear_turn_research_context_removes_ephemeral_messages_and_state() -> None:
    agent = Agent.__new__(Agent)
    agent.messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old evidence", "_ephemeral": True},
        {"role": "user", "content": "keep this"},
    ]
    agent.state = SimpleNamespace(
        research_intent={"task": "old"},
        research_packet={"evidence": ["old"]},
    )

    agent._clear_turn_research_context()

    assert agent.messages == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "keep this"},
    ]
    assert agent.state.research_intent is None
    assert agent.state.research_packet is None


def test_ephemeral_message_is_not_persisted() -> None:
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    saved: list[dict] = []
    orchestrator._message_sink = saved.append
    messages: list[dict] = []

    orchestrator._append_message(
        messages,
        {"role": "user", "content": "evidence", "_ephemeral": True},
    )

    assert messages and messages[0]["_ephemeral"] is True
    assert saved == []
