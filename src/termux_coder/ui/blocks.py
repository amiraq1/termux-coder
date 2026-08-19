from __future__ import annotations

from rich.console import Group
from rich.markdown import Markdown
from rich.text import Text
from textual.widgets import Static

from .. import theme
from .glyphs import current_glyphs


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
    """Render an activity row using the reference tree layout."""
    glyphs = current_glyphs()
    t = Text(glyphs.tree, style=theme.DIM)
    t.append(label, style=f"bold {badge_color or theme.LAVENDER}")
    if path:
        t.append(f" ({path})", style=theme.WHITE)
    if suffix:
        t.append(f" {suffix}", style=theme.DIM)
    return t


def updated_line(path: str, adds: int, rems: int) -> Text:
    glyphs = current_glyphs()
    t = Text(glyphs.last_branch + "Updated ", style=theme.DIM)
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
    glyphs = current_glyphs()
    full = Group(
        Text(f"{glyphs.fold_open} {label} {glyphs.separator} {len(lines)} lines", style=f"bold {theme.LAVENDER}"),
        Markdown(content, code_theme="monokai", hyperlinks=False),
    )
    if len(lines) <= preview_lines:
        return full, None
    preview = Group(
        Text(f"{glyphs.fold_closed} {label} {glyphs.separator} {len(lines)} lines", style=f"bold {theme.LAVENDER}"),
        Text("\n".join(lines[:preview_lines]), style=theme.WHITE),
        Text(
            f"{glyphs.ellipsis} {len(lines) - preview_lines} more lines {glyphs.separator} Ctrl+O to expand",
            style=theme.DIM,
        ),
    )
    return full, preview


def fold_renderables(label: str, content: str, preview_lines: int, content_style: str | None = None) -> tuple[Text, Text | None]:
    """Build expanded and collapsed renderables for long terminal content."""
    lines = content.splitlines() or [""]
    glyphs = current_glyphs()
    style = content_style or theme.WHITE
    expanded = Text(f"{glyphs.fold_open} {label} {glyphs.separator} {len(lines)} lines\n", style=f"bold {theme.LAVENDER}")
    expanded.append(content, style=style)
    if len(lines) <= preview_lines:
        return expanded, None

    collapsed = Text(
        f"{glyphs.fold_closed} {label} {glyphs.separator} {len(lines)} lines\n",
        style=f"bold {theme.LAVENDER}",
    )
    collapsed.append("\n".join(lines[:preview_lines]), style=style)
    collapsed.append(
        f"\n{glyphs.ellipsis} {len(lines) - preview_lines} more lines {glyphs.separator} Ctrl+O to expand",
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
    glyphs = current_glyphs()
    t = Text()
    for item in items:
        if item.get("done"):
            t.append(glyphs.check + " " + item.get("text", ""), style=f"strike {theme.GREEN}")
        else:
            t.append(glyphs.unchecked + " " + item.get("text", ""), style=f"bold {theme.WHITE}")
        t.append("\n")
    return t
