from __future__ import annotations

import asyncio
import time

from termux_coder.ui.provider_picker import ModelPickerScreen


def test_fast_model_navigation_stays_responsive():
    models = tuple(f"model-{index:03d}" for index in range(100))
    picker = ModelPickerScreen("Performance Provider", models, models[0])

    async def scenario() -> tuple[float, int, int]:
        from textual.app import App, ComposeResult

        class Host(App[None]):
            def compose(self) -> ComposeResult:
                yield from ()

        app = Host()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await app.push_screen(picker)
            await pilot.pause()
            view = picker.query_one("#model-list")
            view.focus()
            started = time.perf_counter()
            moves = 100
            for _ in range(moves):
                picker._move_model(1)
                picker._move_model(-1)
            elapsed_ms = (time.perf_counter() - started) * 1000
            await pilot.pause()
            return elapsed_ms, moves * 2, view.index

    elapsed_ms, event_count, final_index = asyncio.run(scenario())
    assert final_index == 0
    assert event_count == 200
    # Generous CI/Termux threshold: this measures 200 local moves only,
    # not provider/network latency or model loading.
    assert elapsed_ms < 500, f"rapid navigation took {elapsed_ms:.1f} ms"
