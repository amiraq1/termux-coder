from __future__ import annotations

import time

from rich.console import Console

from termux_coder.ui.blocks import markdown_fold_renderables


def _large_markdown(blocks: int = 40) -> str:
    sections = ["# Generated answer", "This is a performance fixture, not executable input."]
    for index in range(blocks):
        sections.extend(
            [
                f"## Example {index}",
                "```python",
                f"def function_{index}(value):",
                "    return value * 2",
                "```",
                "",
            ]
        )
    return "\n".join(sections)


def test_large_markdown_highlighting_stays_responsive():
    content = _large_markdown()
    started = time.perf_counter()
    expanded, collapsed = markdown_fold_renderables("ASSISTANT", content, 8)
    build_ms = (time.perf_counter() - started) * 1000

    console = Console(record=True, width=100)
    started = time.perf_counter()
    console.print(expanded)
    render_ms = (time.perf_counter() - started) * 1000

    assert collapsed is not None
    assert "function_39" in console.export_text()
    assert build_ms < 1000, f"Markdown renderable build took {build_ms:.1f} ms"
    assert render_ms < 3000, f"Markdown console render took {render_ms:.1f} ms"
