from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Static

from termux_coder.ui.app import ChatFeed


class _Host(App[None]):
    def compose(self) -> ComposeResult:
        yield ChatFeed(id="feed")


def test_chat_feed_registers_only_conversation_messages():
    async def scenario():
        app = _Host()
        async with app.run_test(size=(80, 20)):
            feed = app.query_one("#feed", ChatFeed)
            user = Static("user prompt")
            assistant = Static("assistant answer")
            tool = Static("tool output")
            await feed.mount(user, assistant, tool)
            feed.register_message(user, "user")
            feed.register_message(assistant, "assistant")

            assert [(role, widget) for role, widget in feed.message_widgets] == [
                ("user", user),
                ("assistant", assistant),
            ]
            assert tool not in [widget for _role, widget in feed.message_widgets]

    asyncio.run(scenario())
