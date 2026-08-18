"""Tests for patch logic (parse, apply, make_diff, recover)."""
from __future__ import annotations

import pytest

from termux_coder.tools.patch import (
    PatchError,
    apply_blocks,
    make_diff,
    parse_blocks,
    recover_simple_patch,
)

PATCH = """<<<<<<< SEARCH
def add(a, b):
    return a - b
=======
def add(a, b):
    return a + b
>>>>>>> REPLACE"""


# ── parse_blocks ────────────────────────────────────────────────────
def test_parse_single_block():
    blocks = parse_blocks(PATCH)
    assert len(blocks) == 1
    find, replace = blocks[0]
    assert "return a - b" in find
    assert "return a + b" in replace


def test_parse_multiple_blocks():
    patch = (
        "<<<<<<< SEARCH\na = 1\n=======\na = 2\n>>>>>>> REPLACE\n"
        "<<<<<<< SEARCH\nb = 3\n=======\nb = 4\n>>>>>>> REPLACE"
    )
    blocks = parse_blocks(patch)
    assert len(blocks) == 2


def test_unterminated_block_rejected():
    with pytest.raises(PatchError, match="unterminated"):
        parse_blocks("<<<<<<< SEARCH\na\n=======")


def test_no_blocks_rejected():
    with pytest.raises(PatchError, match="no SEARCH"):
        parse_blocks("just plain text")


# ── apply_blocks ─────────────────────────────────────────────────
def test_apply_unique_block():
    src = "def add(a, b):\n    return a - b\n"
    out = apply_blocks(src, parse_blocks(PATCH))
    assert "return a + b" in out
    assert "return a - b" not in out


def test_ambiguous_block_rejected():
    with pytest.raises(PatchError, match="ambiguous"):
        apply_blocks("x = 1\nx = 1\n", [("x = 1", "x = 2")])


def test_not_found_rejected():
    with pytest.raises(PatchError, match="not found"):
        apply_blocks("a\n", [("zzz", "y")])


def test_empty_search_on_existing_file_rejected():
    with pytest.raises(PatchError, match="empty SEARCH"):
        apply_blocks("some content", [("", "new content")])


def test_crlf_normalized():
    src = "x = 1\r\ny = 2\r\n"
    out = apply_blocks(src, [("x = 1\ny = 2", "x = 10\ny = 20")])
    assert "x = 10" in out


def test_multiple_blocks_applied_sequentially():
    src = "a = 1\nb = 2\nc = 3\n"
    blocks = [("a = 1", "a = 10"), ("b = 2", "b = 20")]
    out = apply_blocks(src, blocks)
    assert "a = 10" in out
    assert "b = 20" in out
    assert "c = 3" in out


# ── recover_simple_patch ─────────────────────────────────────────
def test_recover_simple_patch_literal_newline():
    source = "x = 1\n"
    result = recover_simple_patch("x = 1\\nx = 99", source)
    assert result == ("x = 1", "x = 99")


def test_recover_simple_patch_rejects_ambiguous():
    source = "x = 1\nx = 1\n"
    assert recover_simple_patch("x = 1\\nx = 99", source) is None


def test_recover_simple_patch_rejects_multiline():
    assert recover_simple_patch("a\\nb\\nc", "a\n") is None


def test_recover_simple_patch_rejects_empty_find():
    assert recover_simple_patch("\\nx = 99", "x = 1\n") is None


# ── make_diff ─────────────────────────────────────────────────────
def test_make_diff_produces_unified_diff():
    diff = make_diff("test.py", "x = 1\n", "x = 2\n")
    assert "--- a/test.py" in diff
    assert "+++ b/test.py" in diff
    assert "-x = 1" in diff
    assert "+x = 2" in diff


def test_make_diff_empty_change():
    diff = make_diff("test.py", "x = 1\n", "x = 1\n")
    assert diff == ""
