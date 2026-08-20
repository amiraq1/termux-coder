import asyncio
from types import SimpleNamespace

from termux_coder.core.agent import Agent
from termux_coder.core.exploration import ExplorationEventStream, ExplorationManager, ExplorationEvent
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

        async def sink(event: ExplorationEvent):
            await ui.on_event("exploration_update", event=event.model_dump(mode="json"))

        stream.subscribe(sink)
        agent = Agent.__new__(Agent)
        agent.jail = WorkspaceJail(tmp_path)
        agent.ui = ui
        agent.settings = SimpleNamespace(exploration_max_tasks=6)
        agent.exploration_stream = stream
        agent.exploration_manager = None

        await agent._run_read_only_exploration("turn_123")

        kinds = [kind for kind, _ in ui.events]
        assert kinds[0] == "exploration_start"
        assert kinds[-1] == "exploration_end"

        updates = [payload["event"] for kind, payload in ui.events if kind == "exploration_update"]

        event_kinds = [e["kind"] for e in updates]
        assert event_kinds.count("task_start") == 6
        assert event_kinds.count("task_completed") == 6

        tool_events = [e for e in updates if e["kind"] == "task_progress"]
        assert tool_events
        assert all("read_file" in e["detail"] for e in tool_events)
        assert len(agent.exploration_manager.tasks) == 6
        assert all(task.status == "completed" for task in agent.exploration_manager.tasks.values())

    asyncio.run(scenario())
