from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
from io import StringIO

from termux_coder.cli import _friendly_reply
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


def test_cli_ui_shows_compact_tool_status_without_arguments_or_result_body() -> None:
    ui = CliUI()
    output = StringIO()
    with redirect_stdout(output):
        asyncio.run(ui.on_event("tool_start", name="read_file", args={"path": "/secret"}))
        asyncio.run(ui.on_event("tool_result", name="read_file", text="sensitive result"))
    rendered = output.getvalue()
    assert "tool read_file" in rendered
    assert "tool done read_file" in rendered
    assert "/secret" not in rendered
    assert "sensitive result" not in rendered


def test_friendly_reply_handles_common_greetings_only() -> None:
    assert _friendly_reply("hi") == "Hello. How can I help you with your project?"
    assert _friendly_reply("  HELLO! ") == "Hello. How can I help you with your project?"
    assert _friendly_reply("create a file") is None
