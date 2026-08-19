from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult

from termux_coder.ui.app import ContextActionBar


class _Host(App[None]):
    def compose(self) -> ComposeResult:
        yield ContextActionBar(id="actions")


def test_context_action_bar_exposes_keyboard_and_touch_actions():
    async def scenario():
        app = _Host()
        async with app.run_test(size=(80, 20)):
            actions = app.query_one("#actions")
            assert actions.query_one("#action-view").label.plain == "View details"
            assert actions.query_one("#action-retry").label.plain == "Retry"
            assert actions.query_one("#action-close").label.plain == "Close"

    asyncio.run(scenario())
