import asyncio
import json
import time
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

from termux_coder.config import Settings
from termux_coder.ui.app import ChatFeed, TermuxCoderApp, TextualUI


TOKEN_CHUNKS = 25_000
ASSISTANT_MESSAGES = 600
TOOL_EVENTS = 1_000
CHUNK_TEXT = "streamed output line with safe ASCII fallback\n"


async def main() -> None:
    workspace = Path("/tmp/termux-coder-tui-stress")
    workspace.mkdir(parents=True, exist_ok=True)
    settings = Settings(workspace=workspace)
    settings.tui_auto_focus = False
    fake_agent = SimpleNamespace(
        settings=settings,
        jail=SimpleNamespace(root=workspace),
        policy=SimpleNamespace(mode=settings.security_mode),
        session_id="tui-stress-test",
    )
    app = TermuxCoderApp(fake_agent, settings=settings)
    ui = TextualUI(app)
    tracemalloc.start()
    started = time.perf_counter()

    async with app.run_test(size=(122, 39)) as pilot:
        await ui.on_event("turn_start")

        token_started = time.perf_counter()
        token_errors = await asyncio.gather(
            *(ui.on_token(CHUNK_TEXT) for _ in range(TOKEN_CHUNKS)),
            return_exceptions=True,
        )
        token_elapsed = time.perf_counter() - token_started

        event_errors = await asyncio.gather(
            *(
                ui.on_event(
                    "read_ok",
                    path=f"workspace/module_{index % 40}.py",
                    lines=80 + index % 20,
                )
                for index in range(TOOL_EVENTS)
            ),
            return_exceptions=True,
        )

        message_started = time.perf_counter()
        for index in range(ASSISTANT_MESSAGES):
            ui._put_markdown_folded(
                "ASSISTANT",
                f"answer {index}: " + ("detail " * 8),
                4,
            )
            if index % 50 == 0:
                await pilot.pause()
        await pilot.pause()
        message_elapsed = time.perf_counter() - message_started

        feed = app.query_one("#feed", ChatFeed)
        before_navigation = len(feed.rendered_widgets)
        feed.select_message(0)
        await pilot.pause()
        first_selected = feed.selected_message
        first_window_widgets = len(feed.rendered_widgets)
        feed.jump_to_last_message()
        await pilot.pause()
        last_selected = feed.selected_message
        last_window_widgets = len(feed.rendered_widgets)

        await ui.on_event("turn_end")
        await pilot.pause()

        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        elapsed = time.perf_counter() - started
        errors = [repr(error) for error in (*token_errors, *event_errors) if isinstance(error, BaseException)]
        result = {
            "status": "PASS" if not errors else "FAIL",
            "token_chunks": TOKEN_CHUNKS,
            "tool_events": TOOL_EVENTS,
            "assistant_messages": ASSISTANT_MESSAGES,
            "token_elapsed_s": round(token_elapsed, 3),
            "message_elapsed_s": round(message_elapsed, 3),
            "total_elapsed_s": round(elapsed, 3),
            "message_records": len(feed.message_records),
            "rendered_widgets_before_navigation": before_navigation,
            "rendered_widgets_after_first": first_window_widgets,
            "rendered_widgets_after_last": last_window_widgets,
            "virtual_window_limit": feed.VIRTUAL_WINDOW,
            "first_selected": first_selected,
            "last_selected": last_selected,
            "feed_children": len(feed.children),
            "current_memory_mb": round(current_bytes / 1024 / 1024, 2),
            "peak_memory_mb": round(peak_bytes / 1024 / 1024, 2),
            "errors": errors[:5],
        }
        print(json.dumps(result, indent=2))
        if errors:
            raise AssertionError(errors[0])
        assert len(feed.message_records) == ASSISTANT_MESSAGES
        assert first_selected == 0
        assert last_selected == ASSISTANT_MESSAGES - 1
        assert first_window_widgets <= feed.VIRTUAL_WINDOW
        assert last_window_widgets <= feed.VIRTUAL_WINDOW

    tracemalloc.stop()


if __name__ == "__main__":
    asyncio.run(main())
