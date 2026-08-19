from __future__ import annotations

import asyncio
import time

from termux_coder.ui.provider_picker import ModelPickerScreen


class _HostApp:
    pass


def _model_catalog(size: int) -> tuple[str, ...]:
    return tuple(
        f"provider-coder-{index:05d}-stable-context-window-128k"
        for index in range(size)
    )


def test_model_picker_handles_large_catalog_and_fast_navigation():
    models = _model_catalog(2000)
    picker = ModelPickerScreen("High Load Provider", models, models[0])

    async def scenario() -> tuple[float, float, int]:
        from textual.app import App, ComposeResult

        class Host(App[None]):
            def compose(self) -> ComposeResult:
                yield from ()

        app = Host()
        async with app.run_test(size=(100, 30)) as pilot:
            await app.push_screen(picker)
            await pilot.pause()
            view = picker.query_one("#model-list")
            view.focus()
            started = time.perf_counter()
            for _ in range(250):
                picker._move_model(1)
            navigation_ms = (time.perf_counter() - started) * 1000
            assert view.index == 250

            started = time.perf_counter()
            picker._rebuild("provider-coder-019")
            await pilot.pause()
            rebuild_ms = (time.perf_counter() - started) * 1000
            return navigation_ms, rebuild_ms, len(picker.models)

    navigation_ms, rebuild_ms, catalog_size = asyncio.run(scenario())
    assert catalog_size == 2000
    assert navigation_ms < 1500, f"250 moves took {navigation_ms:.1f} ms"
    assert rebuild_ms < 2500, f"large-catalog rebuild took {rebuild_ms:.1f} ms"


def test_model_picker_survives_very_large_search_input():
    models = _model_catalog(500)
    picker = ModelPickerScreen("Large Input Provider", models, models[0])
    huge_query = ("x" * 100_000) + "provider-coder-000"

    async def scenario() -> float:
        from textual.app import App, ComposeResult

        class Host(App[None]):
            def compose(self) -> ComposeResult:
                yield from ()

        app = Host()
        async with app.run_test(size=(100, 30)) as pilot:
            await app.push_screen(picker)
            await pilot.pause()
            started = time.perf_counter()
            picker._rebuild(huge_query)
            await pilot.pause()
            return (time.perf_counter() - started) * 1000

    elapsed_ms = asyncio.run(scenario())
    assert elapsed_ms < 2500, f"100k-character search took {elapsed_ms:.1f} ms"
