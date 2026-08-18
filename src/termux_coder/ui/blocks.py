from __future__ import annotations

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
