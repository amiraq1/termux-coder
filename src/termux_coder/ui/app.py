from __future__ import annotations

import time

from rich.markup import escape
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DirectoryTree, Footer, Input, Static
from textual.css.query import NoMatches

from .. import theme
from ..core.agent import Agent
from .approval import ApprovalScreen
from .clipboard import copy_text
from .glyphs import configure_glyphs, current_glyphs
from .messages import MessageRecord
from .base import AgentUI
from .blocks import (
    ExpandableStatic,
    diff_renderable,
    fold_renderables,
    markdown_fold_renderables,
    todos_renderable,
    tool_line,
    updated_line,
)


class ChatFeed(VerticalScroll):
    VIRTUALIZATION_THRESHOLD = 240
    VIRTUAL_WINDOW = 160
    VIRTUAL_RENDER_BATCH = 24

    def __init__(self, owner=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        self.follow_output = True
        self.message_records: list[MessageRecord] = []
        self.rendered_widgets: dict[int, object] = {}
        self.selected_message = -1

    def register_message(self, widget, role: str, text: str = "") -> MessageRecord:
        widget.add_class("conversation-message", f"-{role}")
        record = MessageRecord.create(len(self.message_records), role, text)
        self.message_records.append(record)
        self.rendered_widgets[record.message_id] = widget
        self._prune_rendered_messages()
        return record

    @property
    def virtualization_enabled(self) -> bool:
        return len(self.message_records) > self.VIRTUALIZATION_THRESHOLD

    def _virtual_window(self) -> range:
        if not self.message_records:
            return range(0)
        center = len(self.message_records) - 1
        if not self.follow_output and self.selected_message >= 0:
            center = self.selected_message
        half = self.VIRTUAL_WINDOW // 2
        start = max(0, center - half)
        end = min(len(self.message_records), start + self.VIRTUAL_WINDOW)
        if end - start < self.VIRTUAL_WINDOW:
            start = max(0, end - self.VIRTUAL_WINDOW)
        return range(start, end)

    def _mount_rendered_widget(self, widget, record: MessageRecord) -> None:
        anchor = next(
            (
                self.rendered_widgets[message_id]
                for message_id in sorted(self.rendered_widgets)
                if message_id > record.message_id
            ),
            None,
        )
        if anchor is None:
            self.mount(widget)
        else:
            self.mount(widget, before=anchor)
        self.rendered_widgets[record.message_id] = widget

    def _fallback_render_record(self, record: MessageRecord):
        widget = Static(record.text)
        widget.add_class("conversation-message", f"-{record.role}")
        self._mount_rendered_widget(widget, record)
        return widget

    def _ensure_rendered(self, record: MessageRecord):
        widget = self.rendered_widgets.get(record.message_id)
        if widget is not None:
            return widget
        if self.owner is not None and hasattr(self.owner, "render_message_record"):
            return self.owner.render_message_record(record)
        return self._fallback_render_record(record)

    def _prune_rendered_messages(self) -> None:
        if not self.virtualization_enabled:
            return
        keep = set(self._virtual_window())
        for message_id, widget in list(self.rendered_widgets.items()):
            if message_id not in keep:
                widget.remove()
                self.rendered_widgets.pop(message_id, None)

    def _ensure_virtual_window_rendered(self) -> None:
        if not self.virtualization_enabled:
            return
        window = self._virtual_window()
        if len(window) <= self.VIRTUAL_RENDER_BATCH:
            render_indices = window
        else:
            center = self.selected_message if self.selected_message >= 0 else window.stop - 1
            half = self.VIRTUAL_RENDER_BATCH // 2
            start = max(window.start, center - half)
            stop = min(window.stop, start + self.VIRTUAL_RENDER_BATCH)
            render_indices = range(start, stop)
        for index in render_indices:
            record = self.message_records[index]
            self._ensure_rendered(record)

    def select_message(self, index: int) -> None:
        if not self.message_records:
            return
        index = max(0, min(index, len(self.message_records) - 1))
        self.selected_message = index
        self.follow_output = False
        self._prune_rendered_messages()
        self._ensure_virtual_window_rendered()
        selected_record = self.message_records[index]
        selected_widget = self._ensure_rendered(selected_record)
        for position, record in enumerate(self.message_records):
            widget = self.rendered_widgets.get(record.message_id)
            if widget is not None:
                widget.set_class(position == index, "-selected")
        self.scroll_to_widget(selected_widget, animate=False)
        if self.owner is not None:
            self.owner.set_scroll_button(True)

    def move_message(self, direction: int) -> None:
        if not self.message_records:
            return
        if self.selected_message < 0:
            next_index = 0 if direction > 0 else len(self.message_records) - 1
        else:
            next_index = self.selected_message + direction
        self.select_message(next_index)

    def clear_message_selection(self) -> None:
        self.selected_message = -1
        for widget in self.rendered_widgets.values():
            widget.remove_class("-selected")

    def jump_to_first_message(self) -> None:
        if self.message_records:
            self.select_message(0)

    def jump_to_last_message(self) -> None:
        if not self.message_records:
            return
        self.select_message(len(self.message_records) - 1)
        self.follow_output = True
        if self.owner is not None:
            self.owner.scroll_to_bottom()

    def on_scroll(self, _event: events.Scroll) -> None:
        at_end = self.scroll_y >= self.max_scroll_y - 1
        self.follow_output = at_end
        if self.owner is not None:
            self.owner.set_scroll_button(not at_end)


class ContextActionBar(Horizontal):
    """Keyboard- and touch-friendly actions for the latest assistant answer."""

    def compose(self) -> ComposeResult:
        yield Button("View details", id="action-view")
        yield Button("Copy answer", id="action-copy")
        yield Button("Retry", id="action-retry")
        yield Button("Close", id="action-close")


class WelcomeCard(Static):
    """Compact start card for small terminal screens."""


class PromptInput(Input):
    """Prompt input that preserves the global provider-picker shortcut."""

    def __init__(self, app: "TermuxCoderApp", *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.termux_app = app

    def on_key(self, event) -> None:
        if event.key == "ctrl+a":
            event.stop()
            self.termux_app.action_open_provider_picker()
        elif event.key == "ctrl+up":
            event.stop()
            self.termux_app.action_previous_message()
        elif event.key == "ctrl+down":
            event.stop()
            self.termux_app.action_next_message()
        elif event.key == "ctrl+home":
            event.stop()
            self.termux_app.action_first_message()
        elif event.key == "ctrl+end":
            event.stop()
            self.termux_app.action_last_message()
        elif event.key in {"ctrl+m", "alt+a"}:
            event.stop()
            self.termux_app.action_toggle_context_actions()
        elif event.key == "ctrl+shift+c":
            event.stop()
            self.termux_app.action_copy_last_answer()


class TextualUI(AgentUI):
    def __init__(self, app: "TermuxCoderApp"):
        self.app = app
        self._buf: list[str] = []
        self._t0 = time.time()
        self._stream_widget: Static | None = None
        self._last_flush = 0.0
        self._read_files = 0
        self._read_lines = 0
        self._last_map_signature: tuple | None = None

    def _put(
        self,
        widget,
        message_role: str | None = None,
        message_text: str = "",
    ) -> None:
        feed = self.app.query_one("#feed", ChatFeed)
        feed.mount(widget)
        if message_role:
            feed.register_message(widget, message_role, message_text)
        if feed.follow_output:
            feed.scroll_end(animate=False)

    def _put_markdown_folded(self, label: str, content: str, preview_lines: int):
        expanded, collapsed = markdown_fold_renderables(label, content, preview_lines)
        if collapsed is None:
            widget = Static(expanded)
            self._put(widget, message_role="assistant", message_text=content)
            return widget
        widget = ExpandableStatic(expanded, collapsed)
        self.app.register_expandable(widget)
        self._put(widget, message_role="assistant", message_text=content)
        return widget

    def _put_folded(self, label: str, content: str, preview_lines: int, content_style: str | None = None):
        expanded, collapsed = fold_renderables(label, content, preview_lines, content_style)
        if collapsed is None:
            widget = Static(expanded)
            self._put(widget)
            return widget
        widget = ExpandableStatic(expanded, collapsed)
        self.app.register_expandable(widget)
        self._put(widget)
        return widget

    def _put_diff(self, diff: str) -> None:
        lines = diff.splitlines()
        if len(lines) <= 12:
            self._put(Static(diff_renderable(diff)))
            return
        full = diff_renderable(diff)
        collapsed = diff_renderable("\n".join(lines[:12]))
        glyphs = current_glyphs()
        collapsed.append(
            f"\n{glyphs.fold_closed} DIFF {glyphs.separator} {len(lines)} lines {glyphs.separator} {len(lines) - 12} more {glyphs.separator} Ctrl+O to expand",
            style=theme.DIM,
        )
        widget = ExpandableStatic(full, collapsed)
        self.app.register_expandable(widget)
        self._put(widget)

    async def on_token(self, text: str) -> None:
        self._buf.append(text)
        self.app.add_tokens(max(1, len(text) // 4))

        if self._stream_widget is None:
            self._stream_widget = Static(Text("", style=theme.WHITE))
            self._put(self._stream_widget)

        now = time.monotonic()
        if now - self._last_flush >= 0.15:
            self._flush_stream()

    def _flush_stream(self) -> None:
        if self._stream_widget is not None:
            self._stream_widget.update(
                Text(current_glyphs().tree + "".join(self._buf), style=theme.WHITE)
            )
            feed = self.app.query_one("#feed", ChatFeed)
            if feed.follow_output:
                feed.scroll_end(animate=False)
            self._last_flush = time.monotonic()

    async def on_event(self, kind: str, **payload) -> None:
        self.app.set_phase(kind, payload)
        if kind == "provider_health":
            self.app.update_provider_health(payload)
            return
        if kind == "turn_start":
            self._buf = []
            self._t0 = time.time()
            self.app.set_busy(True)

        elif kind == "assistant_done":
            if self._stream_widget is not None:
                self._flush_stream()
                text = "".join(self._buf).strip()
                stream_widget = self._stream_widget
                self._stream_widget = None
                self._buf = []
                stream_widget.remove()
                if text:
                    widget = self._put_markdown_folded(f"{current_glyphs().diamond} agent", text, 4)
                    self.app.show_context_actions(text, widget)
            else:
                text = "".join(self._buf).strip()
                if text:
                    widget = self._put_markdown_folded(f"{current_glyphs().diamond} agent", text, 4)
                    self.app.show_context_actions(text, widget)
                self._buf = []

        elif kind in ("tool_recovered", "patch_recovered"):
            self._put(
                Static(
                    Text(
                        f"{current_glyphs().retry} recovered: the model returned a text tool call; it was parsed safely",
                        style=theme.DIM,
                    )
                )
            )

        elif kind == "model_route":
            tier = payload.get("tier")
            route_signature = (tier, payload.get("model"), payload.get("reason"))
            if route_signature == getattr(self.app, "_last_route_signature", None) and not payload.get("escalated"):
                return
            self.app._last_route_signature = route_signature
            color = theme.TEAL if tier == "smart" else theme.LAVENDER
            suffix = payload.get("reason", "auto")
            if payload.get("escalated"):
                suffix = "escalated · " + suffix
            self._put(
                Static(
                    tool_line("ROUTE", tier, f"{payload.get('model')} · {suffix}", badge_color=color)
                )
            )

        elif kind == "map_ready":
            # Repository mapping remains internal; keep it out of the activity feed.
            return

        elif kind == "read_ok":
            self._read_files += 1
            self._read_lines += int(payload.get("lines", 0))
            self.app.update_activity("RUNNING", payload.get("path", ""))
            self._put(
                Static(tool_line("READ", payload["path"]), markup=False)
            )

        elif kind == "patch_applied":
            self._put(Static(tool_line("EDIT", payload["path"])))
            self._put(
                Static(
                    updated_line(
                        payload["path"], payload["additions"], payload["removals"]
                    )
                )
            )
            self._put_diff(payload["diff"])

        elif kind == "git_info":
            color = theme.RED if payload.get("danger") else None
            self._put(
                Static(
                    tool_line(
                        "GIT",
                        payload.get("label", ""),
                        payload.get("detail", ""),
                        badge_color=color,
                    )
                )
            )
        elif kind == "git_diff_view":
            self._put_diff(payload["diff"])

        elif kind == "lsp_on":
            self._put(Static(tool_line("LSP", payload.get("server", ""), "connected")))
        elif kind == "lsp_off":
            self._put(Static(Text(f"lsp off · {payload.get('reason', '')}", style=theme.DIM)))
        elif kind == "lsp_diag":
            count = payload.get("count", 0)
            color = theme.GREEN if count == 0 else theme.ORANGE
            self._put(
                Static(
                    tool_line(
                        "LSP",
                        payload.get("path", ""),
                        f"{count} problems · {payload.get('first', '')}",
                        badge_color=color,
                    )
                )
            )

        elif kind == "context_stats":
            total = payload.get("total_tokens", 0)
            budget = payload.get("budget", 1)
            pct = payload.get("usage_pct", 0)
            bar_len = 20
            filled = int(bar_len * pct / 100)
            glyphs = current_glyphs()
            bar = glyphs.block_full * filled + glyphs.block_empty * (bar_len - filled)

            by_priority = payload.get("by_priority", {})
            p0 = by_priority.get(0, 0) / 1000
            p1 = by_priority.get(1, 0) / 1000
            p2 = by_priority.get(2, 0) / 1000

            text = (
                f"Context {bar} {pct:.0f}% · {total/1000:.1f}k / {budget/1000:.1f}k\n"
                f"P0: {p0:.1f}k  P1: {p1:.1f}k  P2: {p2:.1f}k"
            )
            self._put(Static(Text(text, style=theme.DIM)))

        elif kind == "tool_start":
            self._put(Static(tool_line("Running", payload.get("tool", "")), markup=False))
        elif kind == "shell_done":
            command = payload.get("command", "")
            output = payload.get("output", "")
            self._put_folded("SHELL", f"$ {command}\n{output}".rstrip(), 8, "#d7d7e0")

        elif kind == "todos_update":
            items = payload["items"]
            self._put(Static(tool_line("TODOS", f"{len(items)} items")))
            self._put(Static(todos_renderable(items)))

        elif kind == "web_search_started":
            self.app.update_activity("RUNNING", payload.get("query", ""))
            self._put(Static(tool_line("SEARCH", payload.get("provider", ""), payload.get("query", ""))))
        elif kind == "web_search_finished":
            self._put(Static(tool_line("SEARCH", payload.get("provider", ""), f"{payload.get('result_count', 0)} results")))
        elif kind == "web_search_failed":
            self._put(Static(Text(f"SEARCH · failed · {payload.get('error', '')}", style=theme.RED)))
        elif kind == "fetch_page_started":
            self.app.update_activity("RUNNING", payload.get("url", ""))
            self._put(Static(tool_line("FETCH", "direct-page", payload.get("url", ""))))
        elif kind == "fetch_page_finished":
            self._put(Static(tool_line("FETCH", "direct-page", "page loaded")))
        elif kind == "fetch_page_failed":
            self._put(Static(Text(f"FETCH · failed · {payload.get('error', '')}", style=theme.RED)))
        elif kind == "research_packet":
            self._put(Static(tool_line("RESEARCH", payload.get("confidence", ""), f"{payload.get('evidence_count', 0)} evidence")))
        elif kind == "research_failed":
            self._put(Static(Text(f"RESEARCH · failed · {payload.get('error', '')}", style=theme.RED)))
        elif kind == "verification_start":
            self._put(Static(Text("VERIFYING · running project verification", style=theme.ORANGE)))
        elif kind == "verification_result":
            status = payload.get("status", "unknown")
            style = theme.GREEN if status in ("passed", "skipped") else theme.RED
            self._put(Static(Text(
                f"VERIFYING · {status} · exit={payload.get('exit_code')} · {payload.get('duration_ms')}ms",
                style=style,
            )))
        elif kind == "tool_denied":
            self._put(Static(Text(
                f"DENIED · {payload.get('tool', '')} · {payload.get('reason', '')}",
                style=theme.RED,
            )))
        elif kind == "tool_suppressed":
            self._put(Static(Text(
                f"TOOL · {payload.get('tool', '')} skipped · {payload.get('reason', '')}",
                style=theme.DIM,
            )))
        elif kind == "approval_requested":
            self._put(Static(Text(
                f"approval requested · {len(payload.get('calls', []))} operation(s)",
                style=theme.ORANGE,
            )))
        elif kind == "orchestrator_result":
            self._put(Static(Text(
                f"orchestrator · {payload.get('state', '')} {payload.get('error', '')}",
                style=theme.DIM,
            )))
        elif kind == "max_rounds":
            self._put(Static(Text("stopped: too many tool rounds", style="yellow")))

        elif kind == "turn_end":
            self.app.set_phase("turn_end", {})
            self.app.set_busy(False)

    async def request_approval(self, kind: str, payload: dict) -> bool:
        if kind == "patch":
            symbol = payload.get("symbol")
            title = (
                f"Apply {symbol} patch to {payload.get('path')}?"
                if symbol else f"Apply patch to {payload.get('path')}?"
            )
            body = payload.get("diff", "") or payload.get("replacement", "")
        elif kind == "patch_plan":
            title = f"Apply patch plan {payload.get('plan_id', '')}?"
            summary = payload.get("summary", "")
            paths = ", ".join(payload.get("paths", []))
            body = f"{summary}\nFiles: {paths}\n\n{payload.get('diff', '')}"
        elif kind == "rollback_plan":
            title = f"Rollback patch plan {payload.get('plan_id', '')}?"
            body = "Files: " + ", ".join(payload.get("paths", []))
        elif kind == "network":
            title = payload.get("title", "Approve network request?")
            target = payload.get("query") or payload.get("url", "")
            body = (
                f"Provider: {payload.get('provider', '')}\n"
                f"Target: {target}\n\n"
                "Results will be treated as untrusted web data."
            )
        elif kind == "git":
            title = payload.get("title", "Git action?")
            body = payload.get("body", "")
        else:
            title = "Run command?"
            body = payload.get("command", "")
        risk = str(payload.get("risk", "medium")).upper()
        body = f"Risk: {risk}\n\n{body}"
        return await self.app.push_screen_wait(ApprovalScreen(title, body))


class TermuxCoderApp(App):
    TITLE = "agent"

    def render_message_record(self, record: MessageRecord):
        """Rebuild an evicted assistant message without changing its record."""
        expanded, collapsed = markdown_fold_renderables(f"{current_glyphs().diamond} agent", record.text, 4)
        if collapsed is None:
            widget = Static(expanded)
        else:
            widget = ExpandableStatic(expanded, collapsed)
            self.register_expandable(widget)
        widget.add_class("conversation-message", f"-{record.role}")
        feed = self.query_one("#feed", ChatFeed)
        feed._mount_rendered_widget(widget, record)
        return widget
    BINDINGS = [
        Binding("shift+tab", "toggle_mode", "mode", show=False),
        Binding("ctrl+o", "toggle_expand", "expand", show=False),
        Binding("ctrl+t", "toggle_tree", "tree", show=False),
        Binding("ctrl+p", "focus_prompt", "prompt", show=False),
        Binding("ctrl+a", "open_provider_picker", "provider", show=False),
        Binding("ctrl+up", "previous_message", "previous message", show=False),
        Binding("ctrl+down", "next_message", "next message", show=False),
        Binding("ctrl+home", "first_message", "first message", show=False),
        Binding("ctrl+end", "last_message", "last message", show=False),
        Binding("ctrl+m", "toggle_context_actions", "actions", show=False),
        Binding("alt+a", "toggle_context_actions", "actions", show=False),
        Binding("ctrl+shift+c", "copy_last_answer", "copy answer", show=False),
    ]
    CSS = """
    Screen { background: #000000; color: #e6e6f0; }
    Horizontal { height: 1fr; }
    #tree { width: 32; display: none; background: #0e1218; border: tall #232a36; }
    #tree.-visible { display: block; }
    #maincol { width: 1fr; min-width: 0; }
    #header { height: 11; min-height: 11; margin: 0 1; padding: 0 1; background: #000000; color: #e6e6f0; content-align: center middle; }
    #activity { height: 2; margin: 1 1 0 1; padding: 0 0; background: #000000; color: #e6e6f0; }
    ChatFeed { height: 1fr; padding: 0 1; scrollbar-size: 1 1; background: #000000; }
    #welcome { margin: 1 0; padding: 1 2; background: #121a27; border: round #3b4f72; color: #cbd5e1; }
    #status { height: 2; margin: 0 1; padding: 0 0; background: #000000; color: #9ce3cb; }
    #activity.-hidden, #status.-hidden { display: none; }
    ChatFeed .conversation-message.-user { background: #2b2b2b; padding: 0 1; }
    ChatFeed .conversation-message.-selected { background: #18283d; border-left: tall #6ca0ff; }
    #scroll-bottom { height: 1; margin: 0 1; display: none; min-width: 18; }
    #scroll-bottom.-visible { display: block; }
    #actions { height: 3; margin: 0 1; display: none; }
    #actions.-visible { display: block; }
    #actions Button { min-width: 16; margin: 0 1; }
    Input, Input:focus { height: 3; margin: 0 1; padding: 0 0; border: none; border-top: solid #8a8a93; border-bottom: solid #8a8a93; background: #000000; color: #e6e6f0; }
    Footer { display: none; }
    .diff { overflow-x: auto; }
    """

    def __init__(self, agent: Agent, settings=None, store=None):
        super().__init__()
        self.agent = agent
        self.settings = settings or agent.settings
        configure_glyphs(getattr(self.settings, "tui_unicode", "auto"))
        self.store = store
        self._tokens = 0
        self._busy = False
        self._verb = 0
        self._expandables: list[ExpandableStatic] = []
        self._last_route_signature: tuple | None = None
        self._last_map_signature: tuple | None = None
        self._phase = "READY"
        self._activity = "waiting for your request"
        self._provider_health = {"state": "unknown", "latency_ms": None}
        self._last_prompt = ""
        self._last_answer_text = ""
        self._last_answer_widget = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield DirectoryTree(str(self.agent.jail.root), id="tree")
            with Vertical(id="maincol"):
                yield Static(id="header")
                yield Static(id="activity")
                yield ChatFeed(self, id="feed")
                yield Static(id="status")
                yield Button(f"{current_glyphs().down} New output", id="scroll-bottom")
                yield Horizontal(id="actions")
                yield PromptInput(self, id="prompt", placeholder=f"{current_glyphs().pointer}Ask your question{current_glyphs().ellipsis}")

    def on_mount(self) -> None:
        feed = self.query_one("#feed", ChatFeed)
        self._render_header()
        self.update_activity("", "")
        if not self.settings.tui_show_activity:
            self.query_one("#activity").add_class("-hidden")
        if not self.settings.tui_show_status:
            self.query_one("#status").add_class("-hidden")
        self._render_status()
        if self.settings.tui_auto_focus:
            self.call_after_refresh(self.action_focus_prompt)
        self.set_interval(1.6, self._tick)

    # ── State ─────────────────────────────────────────────
    def add_tokens(self, n: int) -> None:
        self._tokens += n
        self._render_status()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._render_status()

    def set_phase(self, kind: str, payload: dict) -> None:
        labels = {
            "turn_start": "EXPLORE",
            "round_start": "EXPLORE",
            "tool_start": "RUNNING",
            "web_search_started": "RUNNING",
            "fetch_page_started": "RUNNING",
            "research_start": "RUNNING",
            "research_packet": "RUNNING",
            "approval_requested": "AWAITING APPROVAL",
            "verification_start": "VERIFYING",
            "verification_result": f"VERIFY {payload.get('status', '')}",
            "turn_end": "READY",
        }
        self._phase = labels.get(kind, self._phase)
        if kind == "turn_start":
            self.update_activity("EXPLORE", "Security & data flow analysis")
        elif kind == "tool_start":
            self.update_activity("RUNNING", str(payload.get("tool", "")))
        elif kind in {"web_search_started", "fetch_page_started", "research_start"}:
            self.update_activity("RUNNING", str(payload.get("tool") or payload.get("query") or payload.get("url") or "research"))
        elif kind == "turn_end":
            self.update_activity("", "")
        self._render_status()

    def update_activity(self, label: str, detail: str = "") -> None:
        glyphs = current_glyphs()
        self._activity = f"{label} {glyphs.separator} {detail}" if detail else label
        text = Text()
        if label == "EXPLORE":
            text.append("EXPLORE", style="bold #ffffff on #6c45f5")
            if detail:
                text.append(f"  ({detail})", style=theme.WHITE)
        elif label == "RUNNING":
            text.append(f"{glyphs.tree}Running", style=theme.DIM)
            if detail:
                text.append(f" ({detail})", style=theme.WHITE)
            text.append(glyphs.ellipsis, style=theme.DIM)
        elif label:
            text.append(self._activity, style=theme.DIM)
        try:
            self.query_one("#activity", Static).update(text)
        except NoMatches:
            pass  # widget not yet mounted; activity label will render on next compose

    @staticmethod
    def _compact_header_value(value: str, limit: int = 34) -> str:
        value = str(value)
        if len(value) <= limit:
            return value
        return value[: limit - 1] + current_glyphs().ellipsis

    def _render_header(self) -> None:
        project = self._compact_header_value(
            self.agent.jail.root.name or str(self.agent.jail.root),
            22,
        )
        provider = self._compact_header_value(self.agent.settings.provider, 16)
        model = self._compact_header_value(self.agent.settings.model, 22)
        glyphs = current_glyphs()
        text = Text(justify="center")
        pixel = glyphs.block_full
        logo_rows = (
            f"{pixel * 3}   {pixel}  {pixel * 4}  {pixel * 4}  {pixel * 4}  {pixel * 4}  {pixel * 4}",
            f"{pixel} {pixel}   {pixel}  {pixel}  {pixel}     {pixel}  {pixel}  {pixel}  {pixel}",
            f"{pixel * 3}   {pixel}  {pixel * 4}  {pixel * 3}  {pixel}  {pixel * 3}  {pixel}  {pixel}",
            f"{pixel} {pixel}   {pixel}  {pixel}  {pixel}     {pixel}  {pixel}  {pixel}  {pixel}",
            f"{pixel} {pixel}   {pixel}  {pixel}  {pixel * 4}  {pixel * 4}  {pixel * 4}  {pixel * 4}",
        )
        for index, row in enumerate(logo_rows):
            text.append(row + "\n", style="bold #f5f5f5" if index < 3 else theme.DIM)
        text.append(
            f"v1.4.0  {glyphs.separator}  {provider}  {glyphs.separator}  {model}\n",
            style=theme.DIM,
        )
        text.append(f"{project}\n", style=theme.DIM)
        text.append("FUTURE PULSE", style="bold #ffffff")
        self.query_one("#header", Static).update(text)

    def update_provider_health(self, payload: dict) -> None:
        self._provider_health = dict(payload)
        self._render_header()

    def _provider_health_label(self) -> str:
        state = self._provider_health.get("state", "unknown")
        glyphs = current_glyphs()
        labels = {
            "unknown": f"{glyphs.status_unknown} unknown",
            "checking": f"{glyphs.status_checking} checking",
            "online": f"{glyphs.status_online} online",
            "degraded": f"{glyphs.status_degraded} degraded",
            "offline": f"{glyphs.status_offline} offline",
            "auth_error": f"{glyphs.status_degraded} auth error",
            "rate_limited": f"{glyphs.status_degraded} rate limited",
        }
        label = labels.get(state, f"{glyphs.status_unknown} unknown")
        latency = self._provider_health.get("latency_ms")
        if state == "online" and isinstance(latency, (int, float)):
            label += f" {latency:.0f}ms"
        return label

    def _provider_health_style(self) -> str:
        state = self._provider_health.get("state", "unknown")
        if state == "online":
            return f"bold {theme.TEAL}"
        if state in {"offline", "auth_error", "rate_limited"}:
            return f"bold {theme.RED}"
        if state in {"checking", "degraded"}:
            return f"bold {theme.ORANGE}"
        return theme.DIM

    def register_expandable(self, widget: ExpandableStatic) -> None:
        self._expandables.append(widget)
        if len(self._expandables) > 30:
            self._expandables.pop(0)

    def _tick(self) -> None:
        if self._busy:
            self._verb += 1
            self._render_status()

    def _render_status(self) -> None:
        glyphs = current_glyphs()
        if self._busy:
            t = Text(f"{glyphs.bullet} Aligning{glyphs.ellipsis}", style="bold #cfc3f7 on #2a2440")
        else:
            t = Text(f"{glyphs.bullet} Ready", style=f"bold {theme.TEAL}")
        t.append(f"  {self._tokens / 1000:.1f}k", style=theme.DIM)
        self.query_one("#status", Static).update(t)

    # ── Shortcuts ─────────────────────────────────────────
    def action_toggle_mode(self) -> None:
        self.agent.policy.mode = (
            "ASK" if self.agent.policy.mode == "READONLY" else "READONLY"
        )
        self._render_header()

    def action_toggle_expand(self) -> None:
        if self._expandables:
            self._expandables[-1].toggle()

    def action_toggle_tree(self) -> None:
        self.query_one("#tree").toggle_class("-visible")

    def action_focus_prompt(self) -> None:
        self.query_one("#prompt", Input).focus()

    def action_open_provider_picker(self) -> None:
        from ..providers.selection import configured_provider_names, provider_catalog
        from .provider_picker import ProviderPickerScreen

        try:
            specs, order = provider_catalog(
                self.settings.providers_config_path or None,
                workspace=self.settings.workspace,
            )
            configured = configured_provider_names(
                specs,
                legacy_api_key=self.settings.openai_api_key,
            )
        except (OSError, ValueError) as exc:
            self.query_one("#feed", ChatFeed).mount(
                Static(Text(f"provider config error: {exc}", style=theme.RED))
            )
            return

        self.push_screen(
            ProviderPickerScreen(
                specs,
                order,
                configured,
                current=self.settings.provider,
            ),
            self._on_provider_selected,
        )

    def _on_provider_selected(self, provider_name: str | None) -> None:
        if not provider_name:
            return
        from .provider_picker import ModelPickerScreen

        try:
            from ..providers.selection import configured_provider_names, provider_catalog

            specs, _ = provider_catalog(
                self.settings.providers_config_path or None,
                workspace=self.settings.workspace,
            )
            spec = specs[provider_name]
            configured = configured_provider_names(
                specs,
                legacy_api_key=self.settings.openai_api_key,
            )
            if provider_name not in configured:
                self.query_one("#feed", ChatFeed).mount(
                    Static(
                        Text(
                            f"provider not configured: set {spec.key_env}",
                            style=theme.ORANGE,
                        )
                    )
                )
                return
            models = spec.models or (self.settings.model,)
            self.push_screen(
                ModelPickerScreen(
                    spec.label or provider_name,
                    models,
                    self.settings.model,
                    next_key=self.settings.tui_model_next_key,
                    prev_key=self.settings.tui_model_prev_key,
                ),
                lambda model: self._on_model_selected(provider_name, model),
            )
        except (KeyError, OSError, ValueError) as exc:
            self.query_one("#feed", ChatFeed).mount(
                Static(Text(f"provider selection error: {exc}", style=theme.RED))
            )

    def _on_model_selected(self, provider_name: str, model: str | None) -> None:
        if not model:
            return
        from ..cli import build_agent

        try:
            self.settings.provider = provider_name
            self.settings.model = model
            self.agent = build_agent(
                self.settings,
                TextualUI(self),
                store=self.store,
                resume_id=self.agent.session_id,
            )
            self._render_header()
            self.query_one("#feed", ChatFeed).mount(
                Static(
                    Text(
                        f"connected: {provider_name} {current_glyphs().separator} {model}",
                        style=theme.TEAL,
                    )
                )
            )
        except Exception as exc:
            self.query_one("#feed", ChatFeed).mount(
                Static(Text(f"provider connection failed: {exc}", style=theme.RED))
            )

    # ── Turn lifecycle ─────────────────────────────────────
    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.clear()
        if not text:
            return
        self._last_prompt = text
        self.hide_context_actions()
        if text.startswith("/"):
            if self._handle_slash(text):
                return
        feed = self.query_one("#feed", ChatFeed)
        line = Text()
        line.append(current_glyphs().pointer, style=f"bold {theme.TEAL}")
        line.append(escape(text), style=f"bold {theme.WHITE}")
        message_widget = Static(line)
        feed.mount(message_widget)
        feed.register_message(message_widget, "user", text)
        feed.scroll_end(animate=False)
        self.run_agent(text)

    def _handle_slash(self, text: str) -> bool:
        import time as _time

        from ..cli import build_agent

        feed = self.query_one("#feed", ChatFeed)

        if text == "/actions":
            self.action_toggle_context_actions()
            return True

        if text == "/sessions":
            rows = [
                f"{s['id']}  {_time.strftime('%m-%d %H:%M', _time.localtime(s['updated_at']))}  {s['title']}"
                + (" ◀" if s["id"] == self.agent.session_id else "")
                for s in (self.store.list_recent() if self.store else [])
            ]
            feed.mount(Static(Text("\n".join(rows) or "no sessions", style=theme.DIM)))
            return True

        if text in {"/fast", "/smart", "/auto"}:
            val = text[1:] if text != "/auto" else None
            self.agent.router.forced = val
            feed.mount(Static(Text(f"router forced to: {val or 'auto'}", style=theme.DIM)))
            return True

        if text == "/new" and self.store:
            self.agent = build_agent(self.settings, TextualUI(self), store=self.store)
            feed.mount(Static(tool_line("SESSION", self.agent.session_id, "new")))
            return True

        if (text == "/resume" or text.startswith("/resume ")) and self.store:
            arg = text.split()[1] if len(text.split()) > 1 else None
            recents = self.store.list_recent()
            if arg:
                pick = next((s for s in recents if s["id"].startswith(arg)), None)
            else:
                others = [s for s in recents if s["id"] != self.agent.session_id]
                pick = others[0] if others else None
            if pick:
                self.agent = build_agent(
                    self.settings, TextualUI(self), store=self.store, resume_id=pick["id"]
                )
                feed.mount(
                    Static(tool_line("SESSION", self.agent.session_id, "resumed"))
                )
            else:
                feed.mount(Static(Text("no session to resume", style=theme.DIM)))
            return True

        return False

    def action_previous_message(self) -> None:
        self.query_one("#feed", ChatFeed).move_message(-1)

    def action_next_message(self) -> None:
        self.query_one("#feed", ChatFeed).move_message(1)

    def action_first_message(self) -> None:
        self.query_one("#feed", ChatFeed).jump_to_first_message()

    def action_last_message(self) -> None:
        self.query_one("#feed", ChatFeed).jump_to_last_message()

    def set_scroll_button(self, visible: bool) -> None:
        try:
            button = self.query_one("#scroll-bottom", Button)
        except NoMatches:
            return
        button.set_class(visible, "-visible")

    def scroll_to_bottom(self) -> None:
        feed = self.query_one("#feed", ChatFeed)
        feed.follow_output = True
        feed.scroll_end(animate=False)
        self.set_scroll_button(False)

    def _mount_context_actions(self) -> None:
        actions = self.query_one("#actions", Horizontal)
        actions.remove_children()
        actions.mount(ContextActionBar())
        actions.add_class("-visible")
        view_button = actions.query_one("#action-view", Button)
        view_button.disabled = not isinstance(self._last_answer_widget, ExpandableStatic)

    def show_context_actions(self, answer: str, widget) -> None:
        self._last_answer_text = answer
        self._last_answer_widget = widget
        self.hide_context_actions()

    def action_toggle_context_actions(self) -> None:
        actions = self.query_one("#actions", Horizontal)
        if actions.has_class("-visible"):
            self.hide_context_actions()
        elif self._last_answer_text:
            self._mount_context_actions()

    def hide_context_actions(self) -> None:
        actions = self.query_one("#actions", Horizontal)
        actions.remove_children()
        actions.remove_class("-visible")

    def action_copy_last_answer(self) -> None:
        if not self._last_answer_text:
            self.notify("No answer available to copy.", severity="warning")
            return
        result = copy_text(self._last_answer_text)
        if result.ok:
            message = "Answer copied to clipboard."
            if result.redacted:
                message += " Sensitive-looking values were redacted."
            self.notify(message, severity="information")
        else:
            self.notify(
                "Clipboard unavailable. Install Termux:API or xclip.",
                severity="warning",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "scroll-bottom":
            self.scroll_to_bottom()
        elif event.button.id == "action-view":
            widget = self._last_answer_widget
            if isinstance(widget, ExpandableStatic):
                widget.toggle()
        elif event.button.id == "action-copy":
            self.action_copy_last_answer()
        elif event.button.id == "action-retry":
            prompt = self._last_prompt
            self.hide_context_actions()
            if prompt:
                self.run_agent(prompt)
        elif event.button.id == "action-close":
            self.hide_context_actions()

    @work(exclusive=True)
    async def run_agent(self, text: str) -> None:
        ui = TextualUI(self)
        self.agent.ui = ui
        self.agent.ctx.ui = ui
        try:
            await self.agent.run_turn(text)
        except Exception as exc:
            from openai import AuthenticationError

            if isinstance(exc, AuthenticationError):
                msg = (
                    "AuthenticationError: the API key is invalid or missing.\n"
                    "Fix: source ~/termux-coder/env_nvidia.sh\n"
                    "Or add the export to ~/.bashrc for future sessions."
                )
            else:
                msg = f"error: {exc}"
            feed = self.query_one("#feed", ChatFeed)
            feed.mount(Static(Text(msg, style=theme.RED)))
            feed.scroll_end(animate=False)
        self.query_one(DirectoryTree).reload()
