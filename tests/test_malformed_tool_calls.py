import json

from termux_coder.core.agent import Agent
from termux_coder.core.orchestrator import AgentOrchestrator


class AuditSpy:
    def __init__(self):
        self.events = []

    def log(self, event, **payload):
        self.events.append((event, payload))


def test_orchestrator_sanitizes_malformed_arguments_before_history() -> None:
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator.audit = AuditSpy()
    orchestrator.registry = object()

    response = orchestrator._adapt_response(
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "apply_patch",
                        "arguments": '{"path":"main.py","patch":"unterminated',
                    },
                }
            ],
        },
        "turn-1",
    )

    stored = response.assistant_message["tool_calls"][0]["function"]["arguments"]
    assert json.loads(stored) == {}
    assert response.tool_calls[0].arguments == {}
    assert orchestrator.audit.events[0][0] == "tool_args_parse_error"
    assert "unterminated" in orchestrator.audit.events[0][1]["raw"]


def test_legacy_agent_sanitizes_malformed_arguments_before_persisting() -> None:
    agent = Agent.__new__(Agent)
    agent.audit = AuditSpy()
    assistant = {
        "tool_calls": [
            {
                "id": "call-2",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path":"main.py"',
                },
            }
        ]
    }

    calls = agent._sanitize_assistant_tool_calls(assistant)

    assert calls is not None
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {}
    assert agent.audit.events[0][0] == "tool_args_parse_error"
