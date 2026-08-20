import asyncio
import pytest
from termux_coder.core.exploration import (
    ExplorationManager,
    ExplorationTaskSpec,
    ExplorationEvent,
)

def test_configure_rejects_more_than_six_tasks():
    manager = ExplorationManager('turn_123', max_tasks=2)
    specs = [ExplorationTaskSpec(task_id=str(i), title=f"task {i}", scope="src") for i in range(3)]

    with pytest.raises(ValueError, match="at most 2"):
        manager.configure(specs)

@pytest.mark.parametrize("tool", ["apply_patch", "write_file", "run_command"])
def test_record_tool_rejects_mutating_tools(tool):
    async def scenario():
        manager = ExplorationManager('turn_123')
        manager.configure([ExplorationTaskSpec(task_id="core", title="core", scope="src")])
        await manager.start_task("core")
        with pytest.raises(PermissionError, match="read-only"):
            await manager.record_tool("core", tool, "blocked")

    asyncio.run(scenario())

def test_parallel_read_only_tasks_emit_bounded_snapshots():
    async def scenario():
        updates = []

        async def on_update(event: ExplorationEvent):
            updates.append(event)

        manager = ExplorationManager('turn_123', max_tasks=2, on_update=on_update)
        specs = [
            ExplorationTaskSpec(task_id="core", title="core subsystem", scope="src/core"),
            ExplorationTaskSpec(task_id="tools", title="tools subsystem", scope="src/tools"),
        ]

        async def worker(task):
            await manager.record_tool(task.task_id, "read_file", f"{task.scope}/agent.py", tokens=120)
            await asyncio.sleep(0.01)
            await manager.record_tool(task.task_id, "search_text", "orchestrator", tokens=30)
            return task.task_id

        result = await manager.run(specs, worker)

        assert set(result) == {"core", "tools"}
        assert all(task.status == "completed" for task in manager.tasks.values())
        assert all(item.status == "running" for item in manager.todos) is False
        assert all(item.status == "completed" for item in manager.todos)

        event_kinds = [event.kind for event in updates]
        assert event_kinds.count("task_start") == 2
        assert event_kinds.count("task_progress") == 4
        assert event_kinds.count("task_completed") == 2

        tasks_snapshot = manager.snapshot()["tasks"]
        assert tasks_snapshot[0]["token_count"] == 150

    asyncio.run(scenario())

def test_event_history_is_bounded_per_task():
    async def scenario():
        manager = ExplorationManager('turn_123', max_events_per_task=2)
        manager.configure([ExplorationTaskSpec(task_id="core", title="core", scope="src")])
        await manager.start_task("core")
        for index in range(5):
            await manager.record_tool("core", "read_file", str(index))

        assert list(manager.task("core").events) == ["READ_FILE 3", "READ_FILE 4"]

    asyncio.run(scenario())

def test_event_stream_fans_out_and_supports_unsubscribe():
    async def scenario():
        from termux_coder.core.exploration import ExplorationEventStream

        stream = ExplorationEventStream()
        first = []
        second = []

        async def first_sink(event):
            first.append(event.kind)

        def second_sink(event):
            second.append(event.kind)

        stream.subscribe(first_sink)
        stream.subscribe(second_sink)
        await stream.publish(ExplorationEvent(kind="task_start", turn_id="turn_123", task_id="core"))
        stream.unsubscribe(second_sink)
        await stream.publish(ExplorationEvent(kind="task_completed", turn_id="turn_123", task_id="core"))

        assert first == ["task_start", "task_completed"]
        assert second == ["task_start"]

    asyncio.run(scenario())

def test_cancel_stops_pending_tasks_before_worker_execution():
    async def scenario():
        manager = ExplorationManager('turn_123', max_tasks=2)
        specs = [
            ExplorationTaskSpec(task_id="one", title="one", scope="src"),
            ExplorationTaskSpec(task_id="two", title="two", scope="src"),
        ]
        started = []

        async def worker(task):
            started.append(task.task_id)
            manager.cancel()
            await asyncio.sleep(0)
            return task.task_id

        result = await manager.run(specs, worker)

        assert result[0] == "one"
        assert result[1] is None
        assert started == ["one"]
        assert manager.snapshot()["cancelled"] is True

    asyncio.run(scenario())

def test_todo_status_events_follow_task_lifecycle():
    async def scenario():
        updates = []
        async def on_update(event):
            updates.append(event.kind)

        manager = ExplorationManager('turn_123', on_update=on_update)
        manager.configure([ExplorationTaskSpec(task_id="core", title="core subsystem", scope="src/core")])

        await manager.start_task("core")
        await manager.finish_task("core", status="completed")

        assert updates == ["task_start", "task_completed"]

        todo = manager.todos[0]
        assert todo.status == "completed"

    asyncio.run(scenario())

def test_cancelled_pending_task_publishes_failed_todo_state():
    async def scenario():
        updates = []
        async def on_update(event):
            updates.append(event)

        manager = ExplorationManager('turn_123', max_tasks=2, on_update=on_update)
        specs = [
            ExplorationTaskSpec(task_id="one", title="one", scope="src"),
            ExplorationTaskSpec(task_id="two", title="two", scope="src"),
        ]

        async def worker(task):
            manager.cancel()
            await asyncio.sleep(0)
            return task.task_id

        await manager.run(specs, worker)

        assert any(t.todo_id == "two" and t.status == "cancelled" for t in manager.todos)

    asyncio.run(scenario())
