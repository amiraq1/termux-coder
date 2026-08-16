import pytest

from termux_coder.tools.patch import PatchError, apply_blocks, parse_blocks

PATCH = """<<<<<<< SEARCH
def add(a, b):
    return a - b
=======
def add(a, b):
    return a + b
>>>>>>> REPLACE"""


def test_apply_unique_block():
    src = "def add(a, b):\n    return a - b\n"
    out = apply_blocks(src, parse_blocks(PATCH))
    assert "return a + b" in out


def test_ambiguous_block_rejected():
    with pytest.raises(PatchError):
        apply_blocks("x = 1\nx = 1\n", [("x = 1", "x = 2")])


def test_not_found_rejected():
    with pytest.raises(PatchError):
        apply_blocks("a\n", [("zzz", "y")])


def test_unterminated_block_rejected():
    with pytest.raises(PatchError):
        parse_blocks("<<<<<<< SEARCH\na\n=======")
