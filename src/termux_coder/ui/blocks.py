from __future__ import annotations

from rich.console import Group
from rich.markdown import Markdown
from rich.text import Text
from textual.widgets import Static

from .. import theme


class ExpandableStatic(Static):
    """Expandable content toggled with Ctrl+O."""

    def __init__(self, full, truncated):
        super().__init__(truncated)
        self.full = full
        self.truncated = truncated
        self.expanded = False

    def toggle(self) -> None:
        self.expanded = not self.expanded
        self.update(self.full if self.expanded else self.truncated)


def tool_line(label: str, path: str, suffix: str = "", badge_color: str | None = None) -> Text:
    t = Text()
    t.append(f" {label} ", style=f"bold #ffffff on {badge_color or theme.PURPLE}")
    t.append(f" [{path}]", style=f"bold {theme.WHITE}")
    if suffix:
        t.append(f" {suffix}", style=theme.DIM)
    return t


def updated_line(path: str, adds: int, rems: int) -> Text:
    t = Text("└─ Updated ", style=theme.DIM)
    t.append(path, style=f"bold {theme.WHITE}")
    t.append(" with ", style=theme.DIM)
    t.append(str(adds), style=f"bold {theme.GREEN}")
    t.append(" additions and ", style=theme.DIM)
    t.append(str(rems), style="bold #f47067")
    t.append(" removals", style=theme.DIM)
    return t


def markdown_fold_renderables(label: str, content: str, preview_lines: int) -> tuple[Group, Group | None]:
    """Render assistant Markdown with highlighted fenced code blocks.

    Rich renders the content only; it is never evaluated or executed. The
    collapsed view intentionally uses plain text so it remains cheap to draw.
    """
    lines = content.splitlines() or [""]
    full = Group(
        Text(f"▾ {label} · {len(lines)} lines", style=f"bold {theme.LAVENDER}"),
        Markdown(content, code_theme="monokai", hyperlinks=False),
    )
    if len(lines) <= preview_lines:
        return full, None
    preview = Group(
        Text(f"▸ {label} · {len(lines)} lines", style=f"bold {theme.LAVENDER}"),
        Text("\n".join(lines[:preview_lines]), style=theme.WHITE),
        Text(
            f"… {len(lines) - preview_lines} more lines · Ctrl+O to expand",
            style=theme.DIM,
        ),
    )
    return full, preview


def fold_renderables(label: str, content: str, preview_lines: int, content_style: str | None = None) -> tuple[Text, Text | None]:
    """Build expanded and collapsed renderables for long terminal content."""
    lines = content.splitlines() or [""]
    style = content_style or theme.WHITE
    expanded = Text(f"▾ {label} · {len(lines)} lines\n", style=f"bold {theme.LAVENDER}")
    expanded.append(content, style=style)
    if len(lines) <= preview_lines:
        return expanded, None

    collapsed = Text(
        f"▸ {label} · {len(lines)} lines\n",
        style=f"bold {theme.LAVENDER}",
    )
    collapsed.append("\n".join(lines[:preview_lines]), style=style)
    collapsed.append(
        f"\n… {len(lines) - preview_lines} more lines · Ctrl+O to expand",
        style=theme.DIM,
    )
    return expanded, collapsed


def diff_renderable(diff_text: str) -> Text:
    """
    Render diffs line by line to preserve code alignment in narrow terminals.
    """
    t = Text()
    for line in diff_text.splitlines():
        if line.startswith("+"):
            t.append(line + "\n", style=f"{theme.ADD_FG} on {theme.ADD_BG}")
        elif line.startswith("-"):
            t.append(line + "\n", style=f"{theme.DEL_FG} on {theme.DEL_BG}")
        elif line.startswith("@@"):
            t.append(line + "\n", style=f"bold {theme.BLUE}")
        else:
            t.append(line + "\n", style=theme.DIM)
    return t


def todos_renderable(items) -> Text:
    t = Text()
    for item in items:
        if item.get("done"):
            t.append("☒ " + item.get("text", ""), style=f"strike {theme.GREEN}")
        else:
            t.append("☐ " + item.get("text", ""), style=f"bold {theme.WHITE}")
        t.append("\n")
    return t
