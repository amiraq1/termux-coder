from rich.text import Text

from rich.console import Console
from rich.markdown import Markdown

from termux_coder.ui.blocks import (
    diff_renderable,
    fold_renderables,
    markdown_fold_renderables,
)


def plain(renderable: Text) -> str:
    return renderable.plain


def test_short_content_is_not_collapsed():
    expanded, collapsed = fold_renderables("ASSISTANT", "one\ntwo", 4)

    assert collapsed is None
    assert plain(expanded).startswith("▾ ASSISTANT · 2 lines")
    assert "one\ntwo" in plain(expanded)


def test_long_content_has_compact_preview_and_full_content():
    content = "\n".join(f"line {i}" for i in range(6))
    expanded, collapsed = fold_renderables("SHELL", content, 2, "#d7d7e0")

    assert collapsed is not None
    assert plain(expanded).startswith("▾ SHELL · 6 lines")
    assert plain(collapsed).startswith("▸ SHELL · 6 lines")
    assert "line 0\nline 1" in plain(collapsed)
    assert "4 more lines · Ctrl+O to expand" in plain(collapsed)
    assert "line 5" in plain(expanded)


def test_markdown_renderer_highlights_fenced_code_without_executing_it():
    content = """Here is code:\n\n```python\ndef greet(name):\n    return f\"Hello {name}\"\n```"""
    expanded, collapsed = markdown_fold_renderables("ASSISTANT", content, 8)

    assert collapsed is None
    assert isinstance(expanded.renderables[1], Markdown)
    console = Console(record=True, width=80)
    console.print(expanded)
    rendered = console.export_text()
    assert "def greet(name):" in rendered
    assert "return f\"Hello {name}\"" in rendered


def test_markdown_renderer_keeps_long_answer_collapsible():
    content = "```javascript\nconst answer = 42;\n```\n" + "\n".join(f"line {i}" for i in range(8))
    expanded, collapsed = markdown_fold_renderables("ASSISTANT", content, 4)

    assert collapsed is not None
    assert "Ctrl+O to expand" in collapsed.renderables[-1].plain
    console = Console(record=True, width=80)
    console.print(expanded)
    assert "const answer = 42;" in console.export_text()


def test_diff_renderable_preserves_line_styles_and_text():
    rendered = diff_renderable("@@ -1 +1 @@\n-old\n+new")

    assert plain(rendered) == "@@ -1 +1 @@\n-old\n+new\n"
