from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
from io import StringIO

from termux_coder.cli import _friendly_reply
from termux_coder.config import Settings
from termux_coder.__main__ import _apply_show_thinking_override
from termux_coder.providers.openai_compat import OpenAICompatProvider
from termux_coder.ui.cli import CliUI


def test_cli_ui_hides_thinking_and_streamed_tokens() -> None:
    ui = CliUI()
    output = StringIO()
    with redirect_stdout(output):
        with ui.thinking():
            asyncio.run(ui.on_token("internal tool-call preamble"))
        asyncio.run(ui.on_event("assistant_done"))
        asyncio.run(ui.on_event("turn_end"))
    assert output.getvalue() == ""


def test_cli_ui_show_thinking_enables_spinner_only() -> None:
    from termux_coder import logo

    assert isinstance(CliUI(show_thinking=True).thinking(), logo.Thinking)
    assert not isinstance(CliUI(show_thinking=False).thinking(), logo.Thinking)


def test_show_thinking_reads_environment(monkeypatch) -> None:
    monkeypatch.setenv("TERMUX_CODER_SHOW_THINKING", "1")
    assert Settings().show_thinking is True


def test_cli_value_overrides_environment(monkeypatch) -> None:
    monkeypatch.setenv("TERMUX_CODER_SHOW_THINKING", "1")
    settings = Settings()
    assert _apply_show_thinking_override(settings, False).show_thinking is False
    assert _apply_show_thinking_override(settings, None).show_thinking is False


def test_cli_ui_quiet_mode_hides_progress_details() -> None:
    ui = CliUI()
    output = StringIO()
    with redirect_stdout(output):
        asyncio.run(ui.on_event("model_route", tier="fast", reason="exploration"))
        asyncio.run(ui.on_event("tool_start", name="read_file", args={"path": "/secret"}))
        asyncio.run(ui.on_event("tool_result", name="read_file", text="sensitive result"))
        asyncio.run(ui.on_event("verification_start"))
    assert output.getvalue() == ""


def test_cli_ui_quiet_mode_keeps_failures_and_rollback_visible() -> None:
    ui = CliUI()
    output = StringIO()
    with redirect_stdout(output):
        asyncio.run(ui.on_event("verification_result", status="failed", stderr="syntax error"))
        asyncio.run(ui.on_event("patch_plan_rollback", plan_id="plan-1", errors=[]))
        asyncio.run(ui.on_event("orchestrator_result", state="failed", error="verification failed"))
    rendered = output.getvalue()
    assert "verify failed" in rendered
    assert "rollback completed" in rendered
    assert "error verification failed" in rendered


def test_cli_ui_shows_compact_tool_status_without_arguments_or_result_body() -> None:
    ui = CliUI(show_thinking=True)
    output = StringIO()
    with redirect_stdout(output):
        asyncio.run(ui.on_event("tool_start", name="read_file", args={"path": "/secret"}))
        asyncio.run(ui.on_event("tool_result", name="read_file", text="sensitive result"))
    rendered = output.getvalue()
    assert "tool read_file" in rendered
    assert "tool done read_file" in rendered
    assert "/secret" not in rendered
    assert "sensitive result" not in rendered


def test_missing_api_key_message_is_english() -> None:
    try:
        OpenAICompatProvider("EMPTY", "https://example.test/v1", "test")
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected missing API key failure")
    assert message.startswith("No valid API key found.")
    assert all(ord(char) < 128 for char in message)


def test_friendly_reply_handles_common_greetings_only() -> None:
    assert _friendly_reply("hi") == "Hello. How can I help you with your project?"
    assert _friendly_reply("  HELLO! ") == "Hello. How can I help you with your project?"
    assert _friendly_reply("create a file") is None
