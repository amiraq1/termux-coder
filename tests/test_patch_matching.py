from __future__ import annotations

import pytest

from termux_coder.tools.patch import (
    PatchAmbiguityError,
    PatchError,
    apply_blocks,
    smart_find_location,
)


def test_smart_find_exact_match_reports_unique_location():
    source = "def add(a, b):\n    return a - b\n"

    result = smart_find_location(source, "def add(a, b):\n    return a - b")

    assert result.line_start == 1
    assert result.line_end == 2
    assert result.match_level == "exact"
    assert result.confidence == 1.0


def test_smart_find_accepts_whitespace_variation():
    source = "value = first + second\n"

    result = smart_find_location(source, "value=first+second")

    assert result.match_level == "whitespace-normalized"
    assert apply_blocks(source, [("value=first+second", "value = result")]) == (
        "value = result\n"
    )


def test_smart_find_accepts_indentation_variation():
    source = "if ready:\n    process()\n"

    result = smart_find_location(source, "if ready:\n  process()")

    assert result.match_level == "indentation-aware"
    assert apply_blocks(source, [("if ready:\n  process()", "if ready:\n    done()")]) == (
        "if ready:\n    done()\n"
    )


def test_smart_find_rejects_ambiguous_exact_match():
    source = "value = 1\nvalue = 1\n"

    with pytest.raises(PatchAmbiguityError, match="ambiguous"):
        smart_find_location(source, "value = 1")

    with pytest.raises(PatchAmbiguityError, match="ambiguous"):
        apply_blocks(source, [("value = 1", "value = 2")])


def test_smart_find_rejects_ambiguous_normalized_match():
    source = "value = first + second\nvalue=first+second\n"

    with pytest.raises(PatchAmbiguityError, match="ambiguous"):
        smart_find_location(source, "value=first + second")


def test_smart_find_rejects_missing_match():
    with pytest.raises(PatchError, match="not found"):
        smart_find_location("value = 1\n", "value = 2")


def test_smart_find_preserves_sequential_block_application():
    source = "a = 1\nb = 2\n"

    result = apply_blocks(
        source,
        [
            ("a=1", "a = 10"),
            ("b = 2", "b = 20"),
        ],
    )

    assert result == "a = 10\nb = 20\n"
