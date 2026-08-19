from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Static

from termux_coder.ui.app import ChatFeed


class _Owner:
    def __init__(self):
        self.button_states = []

    def set_scroll_button(self, visible: bool):
        self.button_states.append(visible)


class _Host(App[None]):
    def compose(self) -> ComposeResult:
        self.owner = _Owner()
        yield ChatFeed(self.owner, id="feed")


def test_chat_feed_follows_output_and_respects_manual_scroll():
    async def scenario():
        app = _Host()
        async with app.run_test(size=(60, 8)) as pilot:
            feed = app.query_one("#feed", ChatFeed)
            await feed.mount(*(Static(f"line {index}") for index in range(40)))
            await pilot.pause()
            feed.scroll_end(animate=False)
            await pilot.pause()
            feed.follow_output = True
            assert feed.scroll_y >= feed.max_scroll_y - 1

            feed.scroll_y = max(0, feed.max_scroll_y - 5)
            feed.on_scroll(None)
            await pilot.pause()
            assert feed.follow_output is False
            assert app.owner.button_states[-1] is True

            feed.scroll_end(animate=False)
            feed.scroll_y = feed.max_scroll_y
            feed.on_scroll(None)
            await pilot.pause()
            assert feed.follow_output is True

    asyncio.run(scenario())
