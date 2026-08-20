from __future__ import annotations

import asyncio

from termux_coder.core.replay import ReplayRunner
from termux_coder.core.trace import TraceStore
from termux_coder.providers.mock import MockResponse
from termux_coder.tools import fs

from tests.e2e.conftest import build_orchestrator


def test_trace_store_persists_replay_safe_arguments_only(tmp_path):
    store = TraceStore(tmp_path / "traces.jsonl")
    store.turn_start(
        "t1",
        "read main.py",
        model="demo",
        task_id="task-read",
        related_paths=["main.py"],
    )
    store.tool_call(
        "t1",
        step=1,
        call_id="c1",
        tool="read_file",
        arguments={"path": "main.py"},
        round_index=0,
        task_id="task-read",
        related_paths=["main.py"],
    )
    store.tool_call(
        "t1",
        step=2,
        call_id="c2",
        tool="run_command",
        arguments={"command": "echo secret"},
        round_index=1,
        task_id="task-read",
        related_paths=["main.py"],
    )
    store.turn_end(
        "t1",
        state="idle",
        rounds=2,
        task_id="task-read",
        related_paths=["main.py"],
    )

    records = store.read("t1")
    assert records[0]["task_id"] == "task-read"
    assert records[0]["related_paths"] == ["main.py"]
    assert all(record["task_id"] == "task-read" for record in records)
    calls = [record for record in records if record["event"] == "tool_call"]
    assert calls[0]["arguments"] == {"path": "main.py"}
    assert "arguments" not in calls[1]
    assert store.list_traces(limit=1)[0]["trace_id"] == "t1"


def test_replay_executes_read_only_tool_without_mutating_live_state(e2e_components, tmp_path):
    components = e2e_components
    components["registry"].register(
        "read_file",
        "Read a workspace file",
        fs.ReadFileArgs,
        fs.read_file,
    )
    store = TraceStore(tmp_path / "traces.jsonl")
    store.turn_start("t2", "read main.py", task_id="task-two")
    store.tool_call(
        "t2",
        step=1,
        call_id="read-1",
        tool="read_file",
        arguments={"path": "main.py"},
        round_index=0,
    )

    before = set(components["state"].read_files)
    result = asyncio.run(
        ReplayRunner(store, components["registry"], components["ctx"]).run("t2")
    )

    assert result[0].status == "ok"
    assert "def greet" in result[0].output
    assert set(components["state"].read_files) == before


def test_orchestrator_trace_contains_tool_timing(e2e_components, tmp_path):
    components = e2e_components
    components["registry"].register(
        "list_dir",
        "List workspace files",
        fs.ListDirArgs,
        fs.list_dir,
    )
    trace = TraceStore(tmp_path / "traces.jsonl")
    orch = build_orchestrator(
        components,
        [MockResponse.with_tool("list-1", "list_dir", {"path": "."}), MockResponse.text("done")],
    )
    orch._trace_store = trace

    result = asyncio.run(
        orch.run_turn([{"role": "user", "content": "list the workspace files"}])
    )

    assert result.state.value == "idle"
    trace_id = trace.list_traces(limit=1)[0]["trace_id"]
    events = trace.read(trace_id)
    assert any(event["event"] == "tool_call" for event in events)
    assert any(event["event"] == "tool_result" for event in events)
    assert any(event["event"] == "turn_end" for event in events)
