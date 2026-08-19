import pytest
import json
from unittest.mock import Mock, AsyncMock

from termux_coder.core.orchestrator import AgentOrchestrator, TurnState
from termux_coder.core.registry import ToolRegistry
from termux_coder.security.policy import PolicyEngine
from termux_coder.security.audit import AuditLog
from termux_coder.models.contracts import ProviderResponse, ToolCall, ToolResult

@pytest.fixture
def base_orchestrator(tmp_path):
    registry = ToolRegistry()
    registry.register("read_file", "desc", Mock(), AsyncMock(return_value="file content"))
    registry.register("git_status", "desc", Mock(), AsyncMock(return_value="clean"))
    registry.register("web_search", "desc", Mock(), AsyncMock(return_value="results"))
    registry.register("fetch_page", "desc", Mock(), AsyncMock(return_value="page content"))

    policy = PolicyEngine("permissive")
    
    audit = AuditLog(tmp_path / "audit.log")
    
    ctx = Mock()
    ctx.state = Mock()
    ctx.state.research_intent = None
    ctx.settings = Mock()
    ctx.settings.research_auto_enabled = False
    ctx.settings.max_output_chars = 8000

    provider = Mock()
    orchestrator = AgentOrchestrator(
        provider=provider,
        registry=registry,
        policy_engine=policy,
        audit=audit,
        ctx=ctx,
        on_event=AsyncMock(),
        message_sink=Mock(),
        message_preparer=lambda x: x,
    )
    async def mock_wait(calls, deadline):
        for ecall in calls:
            orchestrator._pending_approvals[ecall.call.call_id] = ecall
            mock_ecall = Mock()
            mock_ecall.call = ecall.call
            mock_ecall.approved = True
            mock_ecall.is_ready_to_execute = True
            orchestrator._pending_approvals[ecall.call.call_id] = mock_ecall
        return True
    orchestrator._wait_for_approvals = mock_wait
    return orchestrator, provider, audit

@pytest.mark.anyio
async def test_a_isolate_generic_input(base_orchestrator):
    orchestrator, provider, audit = base_orchestrator
    
    # Model attempts to use multiple tools
    provider.chat_stream = AsyncMock(return_value={
        "role": "assistant",
        "content": "Let me check.",
        "tool_calls": [
            {"id": "call_1", "function": {"name": "git_status", "arguments": "{}"}},
            {"id": "call_2", "function": {"name": "web_search", "arguments": "{\"query\": \"iraq\"}"}},
            {"id": "call_3", "function": {"name": "fetch_page", "arguments": "{\"url\": \"http://example.com\"}"}},
            {"id": "call_4", "function": {"name": "read_file", "arguments": "{}"}},
        ]
    })

    messages = [{"role": "user", "content": "iraq"}]
    result = await orchestrator.run_turn(messages)
    
    # Since none of the tools match the intent of "iraq", they are all suppressed.
    # The turn should end gracefully.
    assert result.error is None
    assert result.state == TurnState.IDLE
    assert result.final_text == "Let me check."
    assert len(result.tool_results) == 0

    with open(audit.path, "r") as f:
        log_lines = f.readlines()
    
    suppressed = [json.loads(line) for line in log_lines if "tool_suppressed" in line]
    assert len(suppressed) == 4
    tools = {s["tool"] for s in suppressed}
    assert tools == {"git_status", "web_search", "fetch_page", "read_file"}

@pytest.mark.anyio
async def test_b_workspace_intent(base_orchestrator):
    orchestrator, provider, audit = base_orchestrator
    
    provider.chat_stream = AsyncMock(side_effect=[
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "function": {"name": "read_file", "arguments": "{\"path\": \"main.py\"}"}},
            ]
        },
        {
            "role": "assistant",
            "content": "Summary done.",
        }
    ])

    messages = [{"role": "user", "content": "read main.py and summarize it"}]
    result = await orchestrator.run_turn(messages)
    
    assert result.error is None
    assert result.state == TurnState.IDLE
    assert len(result.tool_results) == 1
    assert result.tool_results[0].tool == "read_file"

@pytest.mark.anyio
async def test_c_git_intent(base_orchestrator):
    orchestrator, provider, audit = base_orchestrator
    
    provider.chat_stream = AsyncMock(side_effect=[
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "function": {"name": "git_status", "arguments": "{}"}},
            ]
        },
        {
            "role": "assistant",
            "content": "Status done.",
        }
    ])

    messages = [{"role": "user", "content": "show git status"}]
    result = await orchestrator.run_turn(messages)
    
    assert result.error is None
    assert result.state == TurnState.IDLE
    assert len(result.tool_results) == 1
    assert result.tool_results[0].tool == "git_status"

@pytest.mark.anyio
async def test_d_network_intent(base_orchestrator):
    orchestrator, provider, audit = base_orchestrator
    
    provider.chat_stream = AsyncMock(side_effect=[
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "function": {"name": "web_search", "arguments": "{\"query\": \"python pathlib\"}"}},
            ]
        },
        {
            "role": "assistant",
            "content": "Search done.",
        }
    ])

    messages = [{"role": "user", "content": "search the web for the latest official Python pathlib documentation"}]
    result = await orchestrator.run_turn(messages)
    
    assert result.error is None
    assert result.state == TurnState.IDLE
    assert len(result.tool_results) == 1
    assert result.tool_results[0].tool == "web_search"

@pytest.mark.anyio
async def test_e_abstract_topic_no_network(base_orchestrator):
    orchestrator, provider, audit = base_orchestrator
    
    provider.chat_stream = AsyncMock(return_value={
        "role": "assistant",
        "content": "I am an AI.",
        "tool_calls": [
            {"id": "call_1", "function": {"name": "web_search", "arguments": "{\"query\": \"python\"}"}},
        ]
    })

    messages = [{"role": "user", "content": "python"}]
    result = await orchestrator.run_turn(messages)
    
    assert result.error is None
    assert result.state == TurnState.IDLE
    assert len(result.tool_results) == 0

    with open(audit.path, "r") as f:
        log_lines = f.readlines()
    
    suppressed = [json.loads(line) for line in log_lines if "tool_suppressed" in line]
    assert len(suppressed) == 1
    assert suppressed[0]["tool"] == "web_search"

@pytest.mark.anyio
async def test_f_state_isolation(base_orchestrator):
    orchestrator, provider, audit = base_orchestrator
    
    provider.chat_stream = AsyncMock(return_value={
        "role": "assistant",
        "content": "No tools.",
        "tool_calls": [
            {"id": "call_1", "function": {"name": "web_search", "arguments": "{\"query\": \"iraq\"}"}},
        ]
    })

    # The previous turn had a search intent
    messages = [
        {"role": "user", "content": "search for python"},
        {"role": "assistant", "content": "found it"},
        {"role": "user", "content": "iraq"}
    ]
    
    result = await orchestrator.run_turn(messages)
    
    # It should only look at the LAST user message ("iraq") which has NO network intent
    assert result.error is None
    assert result.state == TurnState.IDLE
    assert len(result.tool_results) == 0

@pytest.mark.anyio
async def test_g_mixed_response(base_orchestrator):
    orchestrator, provider, audit = base_orchestrator
    
    provider.chat_stream = AsyncMock(side_effect=[
        {
            "role": "assistant",
            "content": "I can help with that.",
            "tool_calls": [
                {"id": "call_1", "function": {"name": "git_status", "arguments": "{}"}},
            ]
        }
    ])

    messages = [{"role": "user", "content": "hello"}]
    result = await orchestrator.run_turn(messages)
    
    assert result.error is None
    assert result.state == TurnState.IDLE
    assert result.final_text == "I can help with that."
    assert len(result.tool_results) == 0

    # The assistant message saved should NOT have tool_calls
    last_saved_msg = messages[-1]
    assert last_saved_msg["role"] == "assistant"
    assert "tool_calls" not in last_saved_msg


@pytest.mark.anyio
async def test_h_pass8_plain_arithmetic_skips_workspace_tools(base_orchestrator):
    orchestrator, provider, audit = base_orchestrator
    provider.chat_stream = AsyncMock(return_value={
        "role": "assistant",
        "content": "The result of 1+1 is 2.",
        "tool_calls": [
            {"id": "call_read", "function": {"name": "read_file", "arguments": "{\"path\": \"1+1\"}"}},
            {"id": "call_search", "function": {"name": "web_search", "arguments": "{\"query\": \"1+1\"}"}},
        ],
    })

    result = await orchestrator.run_turn([{"role": "user", "content": "what is 1+1"}])

    assert result.error is None
    assert result.state == TurnState.IDLE
    assert result.final_text == "The result of 1+1 is 2."
    assert result.tool_results == []
    assert provider.chat_stream.await_count == 1

    with open(audit.path, "r") as f:
        events = [json.loads(line) for line in f if line.strip()]
    suppressed = [event for event in events if event.get("event") == "tool_suppressed"]
    assert {event["tool"] for event in suppressed} == {"read_file", "web_search"}
