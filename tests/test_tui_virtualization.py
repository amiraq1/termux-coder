import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Static

from termux_coder.ui.app import ChatFeed


class _Host(App[None]):
    def compose(self) -> ComposeResult:
        yield ChatFeed(id="feed")


def _register_messages(feed: ChatFeed, count: int) -> list[Static]:
    widgets = []
    for index in range(count):
        text = f"message {index}"
        widget = Static(text)
        widgets.append(widget)
        feed.mount(widget)
        feed.register_message(widget, "assistant", text)
    return widgets


def test_virtualization_keeps_rendered_widgets_within_window():
    async def scenario():
        app = _Host()
        async with app.run_test(size=(80, 20)):
            feed = app.query_one("#feed", ChatFeed)
            _register_messages(feed, ChatFeed.VIRTUALIZATION_THRESHOLD + 60)

            assert feed.virtualization_enabled is True
            assert len(feed.message_records) == ChatFeed.VIRTUALIZATION_THRESHOLD + 60
            assert len(feed.rendered_widgets) <= ChatFeed.VIRTUAL_WINDOW
            assert set(feed.rendered_widgets) == set(range(140, 300))

    asyncio.run(scenario())


def test_virtualization_preserves_records_when_widgets_are_evicted():
    async def scenario():
        app = _Host()
        async with app.run_test(size=(80, 20)):
            feed = app.query_one("#feed", ChatFeed)
            _register_messages(feed, 300)
            original_records = list(feed.message_records)

            feed.select_message(0)

            assert feed.message_records == original_records
            assert len(feed.message_records) == 300
            assert feed.selected_message == 0
            assert 0 in feed.rendered_widgets
            assert len(feed.rendered_widgets) <= ChatFeed.VIRTUAL_WINDOW

    asyncio.run(scenario())


def test_ensure_rendered_rebuilds_evicted_widget():
    async def scenario():
        app = _Host()
        async with app.run_test(size=(80, 20)):
            feed = app.query_one("#feed", ChatFeed)
            _register_messages(feed, 300)
            assert 0 not in feed.rendered_widgets

            record = feed.message_records[0]
            widget = feed._ensure_rendered(record)

            assert widget is feed.rendered_widgets[0]
            assert widget is not None
            assert isinstance(widget, Static)
            assert feed.message_records[0].text == "message 0"

    asyncio.run(scenario())
