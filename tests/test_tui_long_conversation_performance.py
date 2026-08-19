from __future__ import annotations

import asyncio
import time

from textual.app import App, ComposeResult
from textual.widgets import Static

from termux_coder.ui.app import ChatFeed


class _Host(App[None]):
    def compose(self) -> ComposeResult:
        yield ChatFeed(id="feed")


def _conversation_widgets(count: int):
    return [Static(f"{'user' if index % 2 == 0 else 'assistant'} message {index}") for index in range(count)]


def test_tui_handles_1000_message_conversation_and_navigation():
    async def scenario():
        app = _Host()
        async with app.run_test(size=(100, 24)):
            feed = app.query_one("#feed", ChatFeed)
            widgets = _conversation_widgets(1000)
            started = time.perf_counter()
            await feed.mount(*widgets)
            for index, widget in enumerate(widgets):
                feed.register_message(widget, "user" if index % 2 == 0 else "assistant")
            build_ms = (time.perf_counter() - started) * 1000

            feed.jump_to_first_message()
            started = time.perf_counter()
            for _ in range(500):
                feed.move_message(1)
            for _ in range(500):
                feed.move_message(-1)
            navigation_ms = (time.perf_counter() - started) * 1000

            return build_ms, navigation_ms, feed.selected_message, len(feed.message_records)

    build_ms, navigation_ms, selected, message_count = asyncio.run(scenario())
    assert message_count == 1000
    assert selected == 0
    assert build_ms < 8000, f"building 1000 messages took {build_ms:.1f} ms"
    assert navigation_ms < 8000, f"navigating 1000 messages took {navigation_ms:.1f} ms"


def test_tui_home_end_remains_fast_for_long_conversation():
    async def scenario():
        app = _Host()
        async with app.run_test(size=(100, 24)):
            feed = app.query_one("#feed", ChatFeed)
            widgets = _conversation_widgets(1000)
            await feed.mount(*widgets)
            for index, widget in enumerate(widgets):
                feed.register_message(widget, "user" if index % 2 == 0 else "assistant")

            started = time.perf_counter()
            for _ in range(20):
                feed.jump_to_first_message()
                feed.jump_to_last_message()
            elapsed_ms = (time.perf_counter() - started) * 1000
            return elapsed_ms, feed.selected_message, feed.follow_output

    elapsed_ms, selected, follow_output = asyncio.run(scenario())
    assert selected == 999
    assert follow_output is True
    assert elapsed_ms < 3000, f"repeated Home/End took {elapsed_ms:.1f} ms"
