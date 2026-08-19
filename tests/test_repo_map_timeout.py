import asyncio
import time
from types import SimpleNamespace

from termux_coder.core.agent import Agent


class _UI:
    def __init__(self):
        self.events = []

    async def on_event(self, kind, **payload):
        self.events.append((kind, payload))


def test_repo_map_timeout_returns_without_blocking_tui():
    async def scenario():
        ui = _UI()

        def slow_render():
            time.sleep(0.05)
            return "late map"

        agent = Agent.__new__(Agent)
        agent.settings = SimpleNamespace(repo_map_timeout_s=0.01)
        agent.repomap = SimpleNamespace(render_budget=slow_render)
        agent._repo_map_task = None
        agent.ui = ui

        started = time.monotonic()
        result = await agent._render_repo_map_with_timeout()
        elapsed = time.monotonic() - started

        assert result is None
        assert elapsed < 0.04
        assert ui.events[0][0] == "repo_map_timeout"

        # Let the worker finish so the test does not leave background work alive.
        await asyncio.sleep(0.06)

    asyncio.run(scenario())
