import asyncio
import json
import time
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

from termux_coder.config import Settings
from termux_coder.ui.app import ChatFeed, TermuxCoderApp, TextualUI

TOKEN_CHUNKS = 25_000
TOKEN_BATCH = 2_500
TOOL_EVENTS = 1_000
ASSISTANT_MESSAGES = 600
CHUNK_TEXT = "streamed output line with safe ASCII fallback\n"
ESTIMATED_TOKENS_PER_CHUNK = max(1, len(CHUNK_TEXT) // 4)
OUTPUT = Path("/home/ubuntu/termux-coder/performance_report/tui_performance_data.json")


def sample(samples, phase, started, tokens, tracemalloc_started):
    current, peak = tracemalloc.get_traced_memory()
    samples.append(
        {
            "phase": phase,
            "elapsed_s": round(time.perf_counter() - started, 6),
            "estimated_tokens": tokens,
            "current_memory_mb": round(current / 1024 / 1024, 6),
            "peak_memory_mb": round(peak / 1024 / 1024, 6),
            "tracemalloc_active": tracemalloc_started,
        }
    )


async def main() -> None:
    workspace = Path("/tmp/termux-coder-tui-performance-report")
    workspace.mkdir(parents=True, exist_ok=True)
    settings = Settings(workspace=workspace)
    settings.tui_auto_focus = False
    fake_agent = SimpleNamespace(
        settings=settings,
        jail=SimpleNamespace(root=workspace),
        policy=SimpleNamespace(mode=settings.security_mode),
        session_id="tui-performance-report",
    )
    app = TermuxCoderApp(fake_agent, settings=settings)
    ui = TextualUI(app)
    samples = []
    started = time.perf_counter()
    tokens = 0
    tracemalloc.start()

    async with app.run_test(size=(122, 39)) as pilot:
        sample(samples, "baseline", started, tokens, True)
        await ui.on_event("turn_start")

        for batch_start in range(0, TOKEN_CHUNKS, TOKEN_BATCH):
            for _ in range(TOKEN_BATCH):
                await ui.on_token(CHUNK_TEXT)
            tokens += TOKEN_BATCH * ESTIMATED_TOKENS_PER_CHUNK
            await pilot.pause()
            sample(samples, f"stream_batch_{(batch_start // TOKEN_BATCH) + 1}", started, tokens, True)

        for index in range(TOOL_EVENTS):
            await ui.on_event(
                "read_ok",
                path=f"workspace/module_{index % 40}.py",
                lines=80 + index % 20,
            )
        await pilot.pause()
        feed = app.query_one("#feed", ChatFeed)
        sample(samples, "after_tool_events", started, tokens, True)

        for index in range(ASSISTANT_MESSAGES):
            ui._put_markdown_folded(
                "ASSISTANT",
                f"answer {index}: " + ("detail " * 8),
                4,
            )
            if index % 50 == 0:
                await pilot.pause()
        await pilot.pause()
        sample(samples, "after_assistant_messages", started, tokens, True)

        feed.select_message(0)
        await pilot.pause()
        sample(samples, "after_first_message_navigation", started, tokens, True)
        feed.jump_to_last_message()
        await pilot.pause()
        sample(samples, "after_last_message_navigation", started, tokens, True)
        await ui.on_event("turn_end")
        await pilot.pause()
        sample(samples, "final", started, tokens, True)

        current, peak = tracemalloc.get_traced_memory()
        result = {
            "metadata": {
                "terminal_size": [122, 39],
                "token_chunks": TOKEN_CHUNKS,
                "estimated_tokens_per_chunk": ESTIMATED_TOKENS_PER_CHUNK,
                "tool_events": TOOL_EVENTS,
                "assistant_messages": ASSISTANT_MESSAGES,
                "virtual_window_limit": feed.VIRTUAL_WINDOW,
                "virtual_render_batch": feed.VIRTUAL_RENDER_BATCH,
                "measurement": "tracemalloc plus monotonic wall-clock time",
            },
            "summary": {
                "total_elapsed_s": round(time.perf_counter() - started, 6),
                "estimated_tokens": tokens,
                "current_memory_mb": round(current / 1024 / 1024, 6),
                "peak_memory_mb": round(peak / 1024 / 1024, 6),
                "message_records": len(feed.message_records),
                "rendered_widgets": len(feed.rendered_widgets),
                "feed_children": len(feed.children),
            },
            "samples": samples,
        }

    tracemalloc.stop()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"data: {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
