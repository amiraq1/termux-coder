from __future__ import annotations

import time

from rich.markup import escape
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DirectoryTree, Footer, Input, Static

from .. import theme
from ..core.agent import Agent
from .approval import ApprovalScreen
from .base import AgentUI
from .blocks import (
    ExpandableStatic,
    diff_renderable,
    fold_renderables,
    todos_renderable,
    tool_line,
    updated_line,
)


class ChatFeed(VerticalScroll):
    pass


class WelcomeCard(Static):
    """Compact start card for small terminal screens."""


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

    def _put(self, widget) -> None:
        feed = self.app.query_one("#feed", ChatFeed)
        feed.mount(widget)
        feed.scroll_end(animate=False)

    def _put_folded(self, label: str, content: str, preview_lines: int, content_style: str | None = None) -> None:
        expanded, collapsed = fold_renderables(label, content, preview_lines, content_style)
        if collapsed is None:
            self._put(Static(expanded))
            return
        widget = ExpandableStatic(expanded, collapsed)
        self.app.register_expandable(widget)
        self._put(widget)

    def _put_diff(self, diff: str) -> None:
        lines = diff.splitlines()
        if len(lines) <= 12:
            self._put(Static(diff_renderable(diff)))
            return
        full = diff_renderable(diff)
        collapsed = diff_renderable("\n".join(lines[:12]))
        collapsed.append(
            f"\n▸ DIFF · {len(lines)} lines · {len(lines) - 12} more · Ctrl+O to expand",
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
                Text("∷ " + "".join(self._buf), style=theme.WHITE)
            )
            self.app.query_one("#feed", ChatFeed).scroll_end(animate=False)
            self._last_flush = time.monotonic()

    async def on_event(self, kind: str, **payload) -> None:
        self.app.set_phase(kind, payload)
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
                    self._put_folded("ASSISTANT", text, 4)
            else:
                text = "".join(self._buf).strip()
                if text:
                    self._put_folded("ASSISTANT", text, 4)
                self._buf = []

        elif kind in ("tool_recovered", "patch_recovered"):
            self._put(
                Static(
                    Text(
                        "↻ recovered: the model returned a text tool call; it was parsed safely",
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
            self.app.update_activity(
                "READ",
                f"{self._read_files} files · {self._read_lines} lines",
            )
            self._put(
                Static(tool_line("READ", payload["path"], f"{payload['lines']} lines"), markup=False)
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
            bar = "█" * filled + "░" * (bar_len - filled)

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
            self._put(Static(tool_line("TOOL", payload.get("tool", ""), "running"), markup=False))
        elif kind == "shell_done":
            command = payload.get("command", "")
            output = payload.get("output", "")
            self._put_folded("SHELL", f"$ {command}\n{output}".rstrip(), 8, "#d7d7e0")

        elif kind == "todos_update":
            items = payload["items"]
            self._put(Static(tool_line("TODOS", f"{len(items)} items")))
            self._put(Static(todos_renderable(items)))

        elif kind == "web_search_started":
            self.app.update_activity("SEARCH", payload.get("query", ""))
            self._put(Static(tool_line("SEARCH", payload.get("provider", ""), payload.get("query", ""))))
        elif kind == "web_search_finished":
            self._put(Static(tool_line("SEARCH", payload.get("provider", ""), f"{payload.get('result_count', 0)} results")))
        elif kind == "web_search_failed":
            self._put(Static(Text(f"SEARCH · failed · {payload.get('error', '')}", style=theme.RED)))
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
            title = f"Apply patch to {payload.get('path')}?"
            body = payload.get("diff", "")
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
            body = (
                f"Provider: {payload.get('provider', '')}\n"
                f"Query: {payload.get('query', '')}\n\n"
                "Results will be treated as untrusted web data."
            )
        elif kind == "git":
            title = payload.get("title", "Git action?")
            body = payload.get("body", "")
        else:
            title = "Run command?"
            body = payload.get("command", "")
        return await self.app.push_screen(ApprovalScreen(title, body))


class TermuxCoderApp(App):
    TITLE = "◈ agent"
    BINDINGS = [
        Binding("shift+tab", "toggle_mode", "mode", show=False),
        Binding("ctrl+o", "toggle_expand", "expand", show=False),
        Binding("ctrl+t", "toggle_tree", "tree", show=False),
        Binding("ctrl+p", "focus_prompt", "prompt", show=False),
    ]
    CSS = """
    Screen { background: #07090d; color: #e7e9ee; }
    Horizontal { height: 1fr; }
    #tree { width: 32; display: none; background: #0e1218; border: tall #232a36; }
    #tree.-visible { display: block; }
    #maincol { width: 1fr; min-width: 0; }
    #header { height: 2; padding: 0 1; background: #111722; color: #c8d0de; border-bottom: solid #2b3850; }
    ChatFeed { height: 1fr; padding: 1 1; scrollbar-size: 1 1; }
    #welcome { margin: 1 0; padding: 1 2; background: #121a27; border: round #3b4f72; color: #cbd5e1; }
    #activity { height: 1; margin: 0 1; padding: 0 1; background: #111722; color: #9aa6b8; }
    #status { height: 1; margin: 0 1; padding: 0 1; background: #0d1514; color: #9ce3cb; }
    Input { margin: 0 1; border: tall #456fa8; background: #11151c; }
    Footer { display: none; }
    .diff { overflow-x: auto; }
    """

    def __init__(self, agent: Agent, settings=None, store=None):
        super().__init__()
        self.agent = agent
        self.settings = settings or agent.settings
        self.store = store
        self._tokens = 0
        self._busy = False
        self._verb = 0
        self._expandables: list[ExpandableStatic] = []
        self._last_route_signature: tuple | None = None
        self._last_map_signature: tuple | None = None
        self._phase = "READY"
        self._activity = "waiting for your request"

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield DirectoryTree(str(self.agent.jail.root), id="tree")
            with Vertical(id="maincol"):
                yield Static(id="header")
                yield ChatFeed(id="feed")
                yield Static(id="activity")
                yield Static(id="status")
                yield Input(id="prompt", placeholder="Ask your question…")

    def on_mount(self) -> None:
        feed = self.query_one("#feed", ChatFeed)
        self._render_header()
        self.update_activity("READY", "waiting for your request")
        self._render_status()
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
            "turn_start": "THINKING",
            "round_start": "PLANNING",
            "tool_start": "EXECUTING",
            "web_search_started": "SEARCH",
            "approval_requested": "AWAITING APPROVAL",
            "verification_start": "VERIFYING",
            "verification_result": f"VERIFY {payload.get('status', '')}",
            "turn_end": "READY",
        }
        self._phase = labels.get(kind, self._phase)
        detail = payload.get("tool", payload.get("reason", ""))
        self.update_activity(self._phase, detail)
        self._render_status()

    def update_activity(self, label: str, detail: str = "") -> None:
        self._activity = f"{label} · {detail}" if detail else label
        try:
            self.query_one("#activity", Static).update(
                Text(self._activity, style=theme.DIM)
            )
        except Exception:
            pass

    def _render_header(self) -> None:
        project = self.agent.jail.root.name or str(self.agent.jail.root)
        text = Text()
        text.append("◈ agent", style=f"bold {theme.TEAL}")
        text.append(f"  ·  {project}", style=theme.WHITE)
        text.append(f"  ·  {self.agent.settings.model}", style=theme.DIM)
        text.append(
            f"  ·  {self.agent.settings.security_mode}",
            style=f"bold {theme.ORANGE}",
        )
        self.query_one("#header", Static).update(text)

    def register_expandable(self, widget: ExpandableStatic) -> None:
        self._expandables.append(widget)
        if len(self._expandables) > 30:
            self._expandables.pop(0)

    def _tick(self) -> None:
        if self._busy:
            self._verb += 1
            self._render_status()

    def _render_status(self) -> None:
        if self._busy:
            verb = theme.VERBS[self._verb % len(theme.VERBS)]
            t = Text(
                f" ◇ {self._phase} · {verb}… ",
                style="bold #cfc3f7 on #2a2440",
            )
        else:
            t = Text(" ◈ READY ", style=f"bold {theme.TEAL} on #0d2b27")
        t.append(f" · {self._tokens / 1000:.1f}k", style=theme.DIM)
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

    # ── Turn lifecycle ─────────────────────────────────────
    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.clear()
        if not text:
            return
        if text.startswith("/"):
            if self._handle_slash(text):
                return
        feed = self.query_one("#feed", ChatFeed)
        line = Text()
        line.append("❯ ", style=f"bold {theme.TEAL}")
        line.append(escape(text), style=f"bold {theme.WHITE}")
        feed.mount(Static(line))
        feed.scroll_end(animate=False)
        self.run_agent(text)

    def _handle_slash(self, text: str) -> bool:
        import time as _time

        from ..cli import build_agent

        feed = self.query_one("#feed", ChatFeed)

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
