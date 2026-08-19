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

            assert [(record.role, record.text) for record in feed.message_records] == [
                ("user", ""),
                ("assistant", ""),
            ]
            assert list(feed.rendered_widgets.values()) == [user, assistant]
            assert tool not in feed.rendered_widgets.values()

    asyncio.run(scenario())



def test_chat_feed_moves_only_across_registered_messages():
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

            feed.move_message(1)
            assert feed.selected_message == 0
            assert user.has_class("-selected")
            feed.move_message(1)
            assert feed.selected_message == 1
            assert assistant.has_class("-selected")
            feed.move_message(1)
            assert feed.selected_message == 1
            feed.move_message(-1)
            assert feed.selected_message == 0
            assert not tool.has_class("-selected")

    asyncio.run(scenario())



def test_message_navigation_bindings_do_not_replace_provider_shortcut():
    from termux_coder.ui.app import TermuxCoderApp

    bindings = {binding.key: binding.action for binding in TermuxCoderApp.BINDINGS}
    assert bindings["ctrl+up"] == "previous_message"
    assert bindings["ctrl+down"] == "next_message"
    assert bindings["ctrl+a"] == "open_provider_picker"



def test_chat_feed_jumps_to_first_and_last_message():
    async def scenario():
        app = _Host()
        async with app.run_test(size=(80, 20)):
            feed = app.query_one("#feed", ChatFeed)
            first = Static("first")
            middle = Static("middle")
            last = Static("last")
            await feed.mount(first, middle, last)
            feed.register_message(first, "user")
            feed.register_message(middle, "assistant")
            feed.register_message(last, "assistant")

            feed.jump_to_first_message()
            assert feed.selected_message == 0
            assert first.has_class("-selected")
            assert feed.follow_output is False

            feed.jump_to_last_message()
            assert feed.selected_message == 2
            assert last.has_class("-selected")
            assert feed.follow_output is True

    asyncio.run(scenario())


def test_message_navigation_bindings_include_home_end():
    from termux_coder.ui.app import TermuxCoderApp

    bindings = {binding.key: binding.action for binding in TermuxCoderApp.BINDINGS}
    assert bindings["ctrl+home"] == "first_message"
    assert bindings["ctrl+end"] == "last_message"
