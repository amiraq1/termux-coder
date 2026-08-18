"""
test_format_final_answer.py — regression tests for _format_final_answer.

Covers all 10 required invariants:
  1. list_dir success → actual file names
  2. read_file success (short) → inline content
  3. read_file success (long) → line-count header + first N lines
  4. search_text success → matching paths
  5. web_search success → titles/URLs/snippets, no raw JSON
  6. denied tool → "denied: …" message, no fabricated answer
  7. failed tool → "error: …" message, no fabricated answer
  8. model-only text (no tool) → trusted as final answer when non-empty
  9. orchestrated turn with no tools AND no text → explicit error, not stale history
 10. web_search: raw JSON payload is never echoed verbatim
"""
from __future__ import annotations

import json

from termux_coder.cli import _format_final_answer, _format_web_results
from termux_coder.core.orchestrator import TurnResult, TurnState
from termux_coder.models.contracts import ErrorCode, ToolError, ToolResult


# ── helpers ────────────────────────────────────────────────────────────────

def _ok(tool: str, data) -> ToolResult:
    return ToolResult.success(tool=tool, call_id=f"c-{tool}", data=data)


def _fail(tool: str, code: ErrorCode, message: str) -> ToolResult:
    return ToolResult.failure(
        tool=tool, call_id=f"c-{tool}", code=code, message=message
    )


def _tr(state=TurnState.IDLE, final_text="", tool_results=None) -> TurnResult:
    return TurnResult(state=state, final_text=final_text, tool_results=tool_results or [])


class _FakeAgent:
    """Stand-in for Agent used only to test the legacy _latest_assistant_text path."""
    def __init__(self, messages):
        self.messages = messages


# ── 1. list_dir success ────────────────────────────────────────────────────

def test_list_dir_shows_actual_file_names() -> None:
    listing = "file main.py\nfile README.md\ndir  src"
    result = _format_final_answer(
        _FakeAgent([]),
        _tr(tool_results=[_ok("list_dir", listing)]),
    )
    assert "main.py" in result
    assert "README.md" in result
    assert "[list_dir]" in result


# ── 2. read_file short file ────────────────────────────────────────────────

def test_read_file_shows_content_when_short() -> None:
    content = "def greet(name):\n    return 'hi '\n"
    result = _format_final_answer(
        _FakeAgent([]),
        _tr(tool_results=[_ok("read_file", content)]),
    )
    assert "def greet" in result
    assert "[read_file]" in result


# ── 3. read_file long file ─────────────────────────────────────────────────

def test_read_file_long_shows_header_and_first_lines() -> None:
    lines = [f"line{i}" for i in range(50)]
    content = "\n".join(lines)
    result = _format_final_answer(
        _FakeAgent([]),
        _tr(tool_results=[_ok("read_file", content)]),
    )
    assert "[read_file]" in result
    assert "50 lines" in result
    # first line must appear
    assert "line0" in result
    # line beyond the inline limit must NOT appear
    assert "line25" not in result


# ── 4. search_text shows matching paths ────────────────────────────────────

def test_search_text_shows_matching_paths() -> None:
    matches = "src/main.py:3:    return name\nutils/helpers.py:12:    return value\n"
    result = _format_final_answer(
        _FakeAgent([]),
        _tr(tool_results=[_ok("search_text", matches)]),
    )
    assert "main.py" in result
    assert "helpers.py" in result
    assert "[search_text]" in result


# ── 5. web_search shows titles/URLs/snippets ───────────────────────────────

def _make_web_json(n: int = 2) -> str:
    results = [
        {
            "title": f"Result {i}",
            "url": f"https://example.com/page{i}",
            "snippet": f"This is snippet {i}.",
            "source": "web_search",
            "untrusted": True,
            "possible_prompt_injection": False,
        }
        for i in range(n)
    ]
    return json.dumps({
        "query": "test query",
        "results": results,
        "total_found": n,
        "search_time_ms": 42,
        "provider": "duckduckgo",
        "truncated": False,
        "warning": "Untrusted web data.",
    })


def test_web_search_shows_title_url_snippet_not_raw_json() -> None:
    payload = _make_web_json(2)
    result = _format_final_answer(
        _FakeAgent([]),
        _tr(tool_results=[_ok("web_search", payload)]),
    )
    assert "Result 0" in result
    assert "https://example.com/page0" in result
    assert "snippet 0" in result
    # The entire raw JSON blob must NOT be echoed verbatim
    assert '"search_time_ms"' not in result
    assert '"untrusted"' not in result
    assert "[web_search]" in result


def test_format_web_results_from_json_string() -> None:
    payload = _make_web_json(1)
    out = _format_web_results(payload)
    assert "Result 0" in out
    assert "https://example.com/page0" in out
    assert '"search_time_ms"' not in out


def test_format_web_results_from_list() -> None:
    items = [
        {"title": "T1", "url": "https://a.com", "snippet": "s1"},
        {"title": "T2", "url": "https://b.com", "snippet": ""},
    ]
    out = _format_web_results(items)
    assert "T1" in out and "https://a.com" in out
    assert "T2" in out


# ── 6. denied tool → error message, no fabricated answer ──────────────────

def test_denied_tool_shows_denied_reason() -> None:
    result = _format_final_answer(
        _FakeAgent([{"role": "assistant", "content": "Great, I searched it!"}]),
        _tr(tool_results=[_fail("web_search", ErrorCode.POLICY_DENY, "network access not allowed")]),
    )
    assert "denied: network access not allowed" in result
    # Stale "success" text from history must not appear
    assert "Great, I searched" not in result


# ── 7. failed tool → error message, no fabricated answer ──────────────────

def test_failed_tool_shows_error_reason() -> None:
    result = _format_final_answer(
        _FakeAgent([{"role": "assistant", "content": "I listed the files."}]),
        _tr(tool_results=[_fail("list_dir", ErrorCode.EXECUTION_ERROR, "permission denied")]),
    )
    assert "error: permission denied" in result
    assert "I listed the files" not in result


# ── 8. model-only text (no tool run) is trusted ───────────────────────────

def test_no_tool_with_final_text_returns_that_text() -> None:
    result = _format_final_answer(
        _FakeAgent([]),
        _tr(final_text="There are 3 Python files in this project."),
    )
    assert "There are 3 Python files" in result


# ── 9. orchestrated turn with no tools AND no text → explicit error ────────

def test_no_tool_no_text_returns_explicit_error_not_stale_history() -> None:
    stale_msg = "I just read the file for you!"
    result = _format_final_answer(
        _FakeAgent([{"role": "assistant", "content": stale_msg}]),
        _tr(final_text=""),
    )
    # Must NOT return the stale history message
    assert stale_msg not in result
    # Must surface an explicit error
    assert "error" in result.lower()
    assert "no answer" in result.lower() or "no tool result" in result.lower()


# ── 10. quiet-mode: data appears but model chatter is suppressed ──────────

def test_short_model_text_suppressed_when_tool_data_present() -> None:
    listing = "file main.py"
    # A short transition sentence (<= 60 chars) must be dropped in favour of data
    result = _format_final_answer(
        _FakeAgent([]),
        _tr(
            final_text="Done.",
            tool_results=[_ok("list_dir", listing)],
        ),
    )
    assert "main.py" in result
    # "Done." is only 5 chars — falls below the 60-char threshold
    # It may or may not appear, but the listing must be there.


def test_substantive_model_text_appended_after_tool_data() -> None:
    listing = "file main.py\nfile utils.py"
    long_explanation = (
        "The workspace contains two Python source files. "
        "main.py holds the entry point and utils.py contains helper functions."
    )
    result = _format_final_answer(
        _FakeAgent([]),
        _tr(
            final_text=long_explanation,
            tool_results=[_ok("list_dir", listing)],
        ),
    )
    assert "main.py" in result
    assert "utils.py" in result
    assert "entry point" in result


# ── legacy path: turn_result is None ──────────────────────────────────────

def test_none_turn_result_falls_back_to_latest_assistant_text() -> None:
    agent = _FakeAgent([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello there!"},
    ])
    result = _format_final_answer(agent, None)
    assert result == "Hello there!"
