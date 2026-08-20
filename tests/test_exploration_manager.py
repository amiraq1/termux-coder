import asyncio

import pytest

from termux_coder.core.exploration import (
    ExplorationManager,
    ExplorationTaskSpec,
)


def test_configure_rejects_more_than_six_tasks():
    manager = ExplorationManager(max_tasks=2)
    specs = [ExplorationTaskSpec(str(i), f"task {i}", "src") for i in range(3)]

    with pytest.raises(ValueError, match="at most 2"):
        manager.configure(specs)


@pytest.mark.parametrize("tool", ["apply_patch", "write_file", "run_command"])
def test_record_tool_rejects_mutating_tools(tool):
    async def scenario():
        manager = ExplorationManager()
        manager.configure([ExplorationTaskSpec("core", "core", "src")])
        await manager.start_task("core")
        with pytest.raises(PermissionError, match="read-only"):
            await manager.record_tool("core", tool, "blocked")

    asyncio.run(scenario())


def test_parallel_read_only_tasks_emit_bounded_snapshots():
    async def scenario():
        updates = []

        async def on_update(kind, payload):
            updates.append((kind, payload))

        manager = ExplorationManager(max_tasks=2, on_update=on_update)
        specs = [
            ExplorationTaskSpec("core", "core subsystem", "src/core"),
            ExplorationTaskSpec("tools", "tools subsystem", "src/tools"),
        ]

        async def worker(task):
            await manager.record_tool(task.task_id, "read_file", f"{task.scope}/agent.py", tokens=120)
            await asyncio.sleep(0.01)
            await manager.record_tool(task.task_id, "search_text", "orchestrator", tokens=30)
            return task.task_id

        result = await manager.run(specs, worker)

        assert set(result) == {"core", "tools"}
        assert all(task.status == "done" for task in manager.tasks.values())
        assert all(item.status == "running" for item in manager.todos) is False
        assert all(item.status == "done" for item in manager.todos)
        assert [kind for kind, _ in updates].count("exploration_task_start") == 2
        assert [kind for kind, _ in updates].count("exploration_tool_result") == 4
        assert [kind for kind, _ in updates].count("exploration_task_end") == 2
        assert manager.snapshot()["tasks"][0]["token_count"] == 150

    asyncio.run(scenario())


def test_event_history_is_bounded_per_task():
    async def scenario():
        manager = ExplorationManager(max_events_per_task=2)
        manager.configure([ExplorationTaskSpec("core", "core", "src")])
        await manager.start_task("core")
        for index in range(5):
            await manager.record_tool("core", "read_file", str(index))

        assert list(manager.task("core").events) == ["READ_FILE 3", "READ_FILE 4"]

    asyncio.run(scenario())
