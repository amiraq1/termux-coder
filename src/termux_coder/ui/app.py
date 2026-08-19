from __future__ import annotations

import time

from rich.markup import escape
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DirectoryTree, Footer, Input, Static
from textual.css.query import NoMatches

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


class PromptInput(Input):
    """Prompt input that preserves the global provider-picker shortcut."""

    def __init__(self, app: "TermuxCoderApp", *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.termux_app = app

    def on_key(self, event) -> None:
        if event.key == "ctrl+a":
            event.stop()
            self.termux_app.action_open_provider_picker()


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
            self.app.update_activity("RESEARCHING", payload.get("query", ""))
            self._put(Static(tool_line("SEARCH", payload.get("provider", ""), payload.get("query", ""))))
        elif kind == "web_search_finished":
            self._put(Static(tool_line("SEARCH", payload.get("provider", ""), f"{payload.get('result_count', 0)} results")))
        elif kind == "web_search_failed":
            self._put(Static(Text(f"SEARCH · failed · {payload.get('error', '')}", style=theme.RED)))
        elif kind == "fetch_page_started":
            self.app.update_activity("RESEARCHING", payload.get("url", ""))
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
    TITLE = "◈ agent"
    BINDINGS = [
        Binding("shift+tab", "toggle_mode", "mode", show=False),
        Binding("ctrl+o", "toggle_expand", "expand", show=False),
        Binding("ctrl+t", "toggle_tree", "tree", show=False),
        Binding("ctrl+p", "focus_prompt", "prompt", show=False),
        Binding("ctrl+a", "open_provider_picker", "provider", show=False),
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
    #activity.-hidden, #status.-hidden { display: none; }
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
        self._provider_health = {"state": "unknown", "latency_ms": None}

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield DirectoryTree(str(self.agent.jail.root), id="tree")
            with Vertical(id="maincol"):
                yield Static(id="header")
                yield ChatFeed(id="feed")
                yield Static(id="activity")
                yield Static(id="status")
                yield PromptInput(self, id="prompt", placeholder="Ask your question…")

    def on_mount(self) -> None:
        feed = self.query_one("#feed", ChatFeed)
        self._render_header()
        self.update_activity("READY", "waiting for your request")
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
            "turn_start": "THINKING",
            "round_start": "PLANNING",
            "tool_start": "EXECUTING",
            "web_search_started": "RESEARCHING",
            "fetch_page_started": "RESEARCHING",
            "research_start": "RESEARCHING",
            "research_packet": "RESEARCHING",
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
        except NoMatches:
            pass  # widget not yet mounted; activity label will render on next compose

    @staticmethod
    def _compact_header_value(value: str, limit: int = 34) -> str:
        value = str(value)
        if len(value) <= limit:
            return value
        return value[: limit - 1] + "…"

    def _render_header(self) -> None:
        project = self.agent.jail.root.name or str(self.agent.jail.root)
        provider = self._compact_header_value(self.agent.settings.provider, 24)
        model = self._compact_header_value(self.agent.settings.model, 42)
        text = Text()
        text.append("◈ agent", style=f"bold {theme.TEAL}")
        text.append(f"  ·  {project}", style=theme.WHITE)
        text.append(
            f"  ·  {self.agent.settings.security_mode}",
            style=f"bold {theme.ORANGE}",
        )
        text.append("\n")
        text.append("provider: ", style=theme.DIM)
        text.append(provider, style=theme.WHITE)
        text.append("  ·  model: ", style=theme.DIM)
        text.append(model, style=theme.WHITE)
        text.append("  ·  ", style=theme.DIM)
        text.append(
            self._provider_health_label(),
            style=self._provider_health_style(),
        )
        self.query_one("#header", Static).update(text)

    def update_provider_health(self, payload: dict) -> None:
        self._provider_health = dict(payload)
        self._render_header()

    def _provider_health_label(self) -> str:
        state = self._provider_health.get("state", "unknown")
        labels = {
            "unknown": "? unknown",
            "checking": "◌ checking",
            "online": "● online",
            "degraded": "! degraded",
            "offline": "× offline",
            "auth_error": "! auth error",
            "rate_limited": "! rate limited",
        }
        label = labels.get(state, "? unknown")
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
                        f"connected: {provider_name} · {model}",
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
