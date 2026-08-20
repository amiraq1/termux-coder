from termux_coder.context import PriorityEngine, TurnBundle
from termux_coder.core.session import SessionStore


def test_turn_bundle_has_per_turn_and_stable_task_identity():
    first = TurnBundle.create("  Fix  auth.py  ", session_id="session-1")
    second = TurnBundle.create("fix auth.py", session_id="session-1")
    other_task = TurnBundle.create("fix auth.py", session_id="session-2")

    assert first.turn_id != second.turn_id
    assert first.task_id == second.task_id
    assert first.task_id != other_task.task_id
    assert first.task_id.startswith("task-")
    assert "auth.py" not in first.task_id


def test_priority_engine_preserves_bundle_metadata():
    item = PriorityEngine.classify(
        {
            "role": "tool",
            "content": "read result",
            "tool_call_id": "call-1",
            "turn_id": "turn-1",
            "task_id": "task-1",
        },
        seq=3,
        current_seq=3,
        latest_user_seq=None,
    )

    assert item.metadata["tool_call_id"] == "call-1"
    assert item.metadata["turn_id"] == "turn-1"
    assert item.metadata["task_id"] == "task-1"


def test_bundle_metadata_roundtrips_through_session_store(tmp_path):
    store = SessionStore(tmp_path / "bundle.db")
    sid = store.create("/w", "m")
    message = {
        "role": "tool",
        "content": "read result",
        "tool_call_id": "call-1",
        "turn_id": "turn-1",
        "task_id": "task-1",
    }

    store.save_message(sid, 0, message)
    loaded = store.load_messages(sid)

    assert loaded == [message]


def test_active_task_bundle_is_preserved_during_compaction():
    from termux_coder.context import BudgetManager, ContextAssembler, ContextItem, TokenEstimator

    estimator = TokenEstimator()
    assembler = ContextAssembler(
        estimator,
        BudgetManager(max_tokens=40, output_reserve=10, estimator=estimator),
    )
    items = [
        ContextItem(
            content="system prompt " * 8,
            kind="system",
            priority=0,
            compressible=False,
        ),
        ContextItem(
            content="old unrelated context " * 30,
            kind="user",
            priority=5,
            metadata={"task_id": "task-old", "turn_id": "turn-old"},
        ),
        ContextItem(
            content="active file context " * 30,
            kind="assistant",
            priority=5,
            metadata={"task_id": "task-active", "turn_id": "turn-active"},
        ),
        ContextItem(
            content="active tool result " * 30,
            kind="tool",
            priority=4,
            metadata={
                "task_id": "task-active",
                "turn_id": "turn-active",
                "tool_call_id": "call-active",
            },
        ),
    ]

    messages = assembler.assemble(
        items,
        current_task="continue active task",
        active_task_id="task-active",
    )
    contents = [message["content"] for message in messages]

    assert any("active file context" in content for content in contents)
    assert any("active tool result" in content for content in contents)
    assert not any(
        content.startswith("old unrelated context")
        for content in contents
    )
    assert any(
        message["role"] == "system" and "Requested: old unrelated context" in message["content"]
        for message in messages
    )
    assert all("task_id" not in message for message in messages)
    assert all("turn_id" not in message for message in messages)


def test_orchestrator_append_tags_execution_messages():
    from termux_coder.core.orchestrator import AgentOrchestrator

    persisted = []
    orchestrator = object.__new__(AgentOrchestrator)
    orchestrator._turn_id = "turn-42"
    orchestrator._task_id = "task-42"
    orchestrator._message_sink = persisted.append
    messages = []

    orchestrator._append_message(
        messages,
        {"role": "tool", "tool_call_id": "call-42", "content": "ok"},
    )

    expected = {
        "role": "tool",
        "tool_call_id": "call-42",
        "content": "ok",
        "turn_id": "turn-42",
        "task_id": "task-42",
    }
    assert messages == [expected]
    assert persisted == [expected]


def test_related_paths_are_normalized_and_restricted():
    bundle = TurnBundle.create("inspect files", session_id="session-1")
    enriched = bundle.add_paths(["src\\main.py", "src/main.py", "../escape.py", "/tmp/outside"])

    assert enriched.related_paths == ("src/main.py",)
    assert bundle.related_paths == ()


def test_agent_related_paths_use_workspace_jail(tmp_path):
    from termux_coder.core.agent import Agent
    from termux_coder.security.jail import WorkspaceJail

    (tmp_path / "main.py").write_text("pass", encoding="utf-8")
    agent = object.__new__(Agent)
    agent.jail = WorkspaceJail(tmp_path)
    agent._active_bundle = TurnBundle.create("inspect files", session_id="session-1")

    agent._extend_active_bundle_paths(["main.py", "../escape.py", "/tmp/outside"])

    assert agent._active_bundle.related_paths == ("main.py",)


def test_related_paths_roundtrip_through_session_store(tmp_path):
    store = SessionStore(tmp_path / "bundle-paths.db")
    sid = store.create("/w", "m")
    message = {
        "role": "tool",
        "content": "read result",
        "turn_id": "turn-1",
        "task_id": "task-1",
        "related_paths": ["src/main.py"],
    }

    store.save_message(sid, 0, message)
    assert store.load_messages(sid) == [message]


def test_related_path_overlap_keeps_old_context_in_compaction():
    from termux_coder.context import BudgetManager, ContextAssembler, ContextItem, TokenEstimator

    estimator = TokenEstimator()
    assembler = ContextAssembler(
        estimator,
        BudgetManager(max_tokens=30, output_reserve=10, estimator=estimator),
    )
    items = [
        ContextItem(content="system " * 8, kind="system", priority=0, compressible=False),
        ContextItem(
            content="auth context " * 30,
            kind="assistant",
            priority=5,
            metadata={"task_id": "task-old", "related_paths": ["auth.py"]},
        ),
        ContextItem(
            content="unrelated context " * 30,
            kind="assistant",
            priority=5,
            metadata={"task_id": "task-old", "related_paths": ["other.py"]},
        ),
    ]

    messages = assembler.assemble(
        items,
        current_task="fix auth",
        active_task_id="task-current",
        active_related_paths={"auth.py"},
    )
    contents = [message["content"] for message in messages]

    assert any("auth context" in content for content in contents)
    assert not any(content.startswith("unrelated context") for content in contents)


def test_orchestrator_records_only_jail_relative_call_paths(tmp_path):
    from types import SimpleNamespace
    from termux_coder.core.orchestrator import AgentOrchestrator
    from termux_coder.models.contracts import ToolCall
    from termux_coder.security.jail import WorkspaceJail

    (tmp_path / "main.py").write_text("pass", encoding="utf-8")
    orchestrator = object.__new__(AgentOrchestrator)
    orchestrator.ctx = SimpleNamespace(jail=WorkspaceJail(tmp_path))
    orchestrator._related_paths = set()

    call = ToolCall(
        call_id="call-plan",
        turn_id="turn-plan",
        name="apply_patch_plan",
        arguments={
            "operations": [
                {"path": "main.py", "patch": "..."},
                {"path": "../escape.py", "patch": "..."},
            ]
        },
    )
    orchestrator._record_call_paths(call)

    assert orchestrator._related_paths == {"main.py"}
