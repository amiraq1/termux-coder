import asyncio
from types import SimpleNamespace

from termux_coder.core.agent import Agent
from termux_coder.core.exploration import ExplorationEventStream, ExplorationManager
from termux_coder.security.jail import WorkspaceJail


class EventUI:
    def __init__(self):
        self.events = []

    async def on_event(self, kind, **payload):
        self.events.append((kind, payload))


def test_read_only_exploration_acceptance_cycle(tmp_path):
    async def scenario():
        (tmp_path / "src/termux_coder/core").mkdir(parents=True)
        (tmp_path / "src/termux_coder/tools").mkdir(parents=True)
        (tmp_path / "src/termux_coder/providers").mkdir(parents=True)
        (tmp_path / "src/termux_coder/security").mkdir(parents=True)
        (tmp_path / "src/termux_coder/models").mkdir(parents=True)
        (tmp_path / "src/termux_coder/ui").mkdir(parents=True)
        (tmp_path / "tests").mkdir()
        (tmp_path / "README.md").write_text("# test repository", encoding="utf-8")
        for path in (
            "src/termux_coder/core/agent.py",
            "src/termux_coder/tools/fs.py",
            "src/termux_coder/providers/router.py",
            "src/termux_coder/security/policy.py",
            "src/termux_coder/models/contracts.py",
            "src/termux_coder/ui/app.py",
            "tests/test_one.py",
        ):
            file_path = tmp_path / path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text("value = 1\n", encoding="utf-8")

        ui = EventUI()
        stream = ExplorationEventStream()

        async def sink(kind, payload):
            await ui.on_event(kind, **payload)

        stream.subscribe(sink)
        agent = Agent.__new__(Agent)
        agent.jail = WorkspaceJail(tmp_path)
        agent.ui = ui
        agent.exploration_stream = stream
        agent.exploration_manager = ExplorationManager(
            max_tasks=6,
            on_update=stream,
        )

        await agent._run_read_only_exploration()

        kinds = [kind for kind, _ in ui.events]
        assert kinds[0] == "exploration_start"
        assert kinds[-1] == "exploration_end"
        assert kinds.count("exploration_task_start") == 6
        assert kinds.count("exploration_task_end") == 6
        tool_events = [payload for kind, payload in ui.events if kind == "exploration_tool_result"]
        assert tool_events
        assert all(event["tool"] == "read_file" for event in tool_events)
        assert all(event["task"]["status"] in {"running", "done"} for event in tool_events)
        assert len(agent.exploration_manager.tasks) == 6
        assert all(task.status == "done" for task in agent.exploration_manager.tasks.values())

    asyncio.run(scenario())
