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
