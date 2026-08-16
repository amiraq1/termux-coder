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
    todos_renderable,
    tool_line,
    updated_line,
)


class ChatFeed(VerticalScroll):
    pass


class TextualUI(AgentUI):
    def __init__(self, app: "TermuxCoderApp"):
        self.app = app
        self._buf: list[str] = []
        self._t0 = time.time()

    def _put(self, widget) -> None:
        feed = self.app.query_one("#feed", ChatFeed)
        feed.mount(widget)
        feed.scroll_end(animate=False)

    def _put_diff(self, diff: str) -> None:
        lines = diff.splitlines()
        full = diff_renderable(diff)
        limit = 14
        if len(lines) > limit:
            trunc = diff_renderable("\n".join(lines[:limit]))
            trunc.append(
                f"\n… (+{len(lines) - limit} more lines) [ctrl+o to expand]",
                style=theme.DIM,
            )
            widget = ExpandableStatic(full, trunc)
            self.app.register_expandable(widget)
        else:
            widget = Static(full)
        self._put(widget)

    async def on_token(self, text: str) -> None:
        self._buf.append(text)
        self.app.add_tokens(max(1, len(text) // 4))

    async def on_event(self, kind: str, **payload) -> None:
        if kind == "turn_start":
            self._buf = []
            self._t0 = time.time()
            self.app.set_busy(True)

        elif kind == "assistant_done":
            secs = int(time.time() - self._t0) or 1
            self._put(Static(Text(f"✳ Thought for {secs} second(s)", style=theme.DIM)))
            text = "".join(self._buf).strip()
            if text:
                self._put(Static(Text(f"∷ {text}", style=theme.WHITE)))
            self._buf = []

        elif kind == "map_ready":
            self._put(
                Static(
                    tool_line(
                        "MAP",
                        f"{payload.get('files')} files · {payload.get('symbols')} symbols",
                        "auto",
                    )
                )
            )

        elif kind == "read_ok":
            self._put(
                Static(tool_line("READ", payload["path"], f"{payload['lines']} lines"))
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

        elif kind == "shell_done":
            self._put(Static(tool_line("SHELL", payload["command"])))
            lines = payload["output"].splitlines()
            full = Text("\n".join(lines), style="#d7d7e0")
            if len(lines) > 8:
                trunc = Text("\n".join(lines[:8]), style="#d7d7e0")
                trunc.append(
                    f"\n… +{len(lines) - 8} lines [ctrl+o to expand]", style=theme.DIM
                )
                widget = ExpandableStatic(full, trunc)
                self.app.register_expandable(widget)
            else:
                widget = Static(full)
            self._put(widget)

        elif kind == "todos_update":
            items = payload["items"]
            self._put(Static(tool_line("TODOS", f"{len(items)} items")))
            self._put(Static(todos_renderable(items)))

        elif kind == "max_rounds":
            self._put(Static(Text("stopped: too many tool rounds", style="yellow")))

        elif kind == "turn_end":
            self.app.set_busy(False)

    async def request_approval(self, kind: str, payload: dict) -> bool:
        if kind == "patch":
            title = f"Apply patch to {payload.get('path')}?"
            body = payload.get("diff", "")
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
        Binding("shift+tab", "toggle_mode", "mode", show=True),
        Binding("ctrl+o", "toggle_expand", "expand", show=True),
        Binding("ctrl+t", "toggle_tree", "tree", show=True),
    ]
    CSS = """
    Screen { background: #000000; }
    Horizontal { height: 1fr; }
    DirectoryTree { width: 30; display: none; }
    DirectoryTree.-visible { display: block; }
    #maincol { width: 1fr; }
    ChatFeed { height: 1fr; padding: 0 1; }
    #status { height: 1; margin: 0 1; }
    Input { margin: 0 1; }
    #modeline { height: 2; margin: 0 1; }
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

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield DirectoryTree(str(self.agent.jail.root), id="tree")
            with Vertical(id="maincol"):
                yield ChatFeed(id="feed")
                yield Static(id="status")
                yield Input(id="prompt", placeholder="Ask your question...")
                yield Static(id="modeline")
        yield Footer()

    def on_mount(self) -> None:
        feed = self.query_one("#feed", ChatFeed)
        intro = Text()
        intro.append("◈ agent\n", style=f"bold {theme.TEAL}")
        intro.append(
            f"project: {self.agent.jail.root}\n"
            f"model: {self.agent.settings.model}\n"
            f"security: {self.agent.settings.security_mode}\n",
            style=theme.DIM,
        )
        feed.mount(Static(intro))
        feed.mount(
            Static(
                tool_line(
                    "SESSION",
                    self.agent.session_id or "-",
                    "resumed" if self.agent.resumed else "new",
                )
            )
        )
        self._render_modeline()
        self._render_status()
        self.set_interval(1.6, self._tick)

    # ── الحالة ─────────────────────────────────────────────
    def add_tokens(self, n: int) -> None:
        self._tokens += n
        self._render_status()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._render_status()

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
            t = Text(f" ◇ {verb}… ", style="bold #cfc3f7 on #2a2440")
        else:
            t = Text(f" ◈ idle ", style=f"bold {theme.TEAL} on #0d2b27")
        t.append(f" {self._tokens / 1000:.1f}k", style=theme.DIM)
        self.query_one("#status", Static).update(t)

    def _render_modeline(self) -> None:
        el = self.query_one("#modeline", Static)
        tail = Text(" [shift+tab]\n? for shortcuts", style=theme.DIM)
        if self.agent.policy.mode == "READONLY":
            el.update(Text("plan mode", style=f"bold {theme.ORANGE}") + tail)
        else:
            el.update(Text("» accept edits on", style=f"bold {theme.LAVENDER}") + tail)

    # ── الاختصارات ─────────────────────────────────────────
    def action_toggle_mode(self) -> None:
        self.agent.policy.mode = (
            "ASK" if self.agent.policy.mode == "READONLY" else "READONLY"
        )
        self._render_modeline()

    def action_toggle_expand(self) -> None:
        if self._expandables:
            self._expandables[-1].toggle()

    def action_toggle_tree(self) -> None:
        self.query_one("#tree").toggle_class("-visible")

    # ── الدورة ─────────────────────────────────────────────
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
                    "AuthenticationError: مفتاح API غير صحيح أو غير مُحمّل.\n"
                    "الحل: source ~/termux-coder/env_nvidia.sh\n"
                    "أو أضف السطر إلى ~/.bashrc ليُحمّل تلقائيًا في كل جلسة."
                )
            else:
                msg = f"error: {exc}"
            feed = self.query_one("#feed", ChatFeed)
            feed.mount(Static(Text(msg, style=theme.RED)))
            feed.scroll_end(animate=False)
        self.query_one(DirectoryTree).reload()
