import locale
from types import SimpleNamespace

from termux_coder.ui import glyphs


def test_ascii_mode_uses_portable_glyphs():
    selected = glyphs.glyphs_for("ascii")

    assert selected.tree == "| "
    assert selected.pointer == "> "
    assert selected.ellipsis == "..."
    assert selected.fold_closed == ">"
    assert selected.check == "[x]"
    assert selected.block_full == "#"


def test_unicode_mode_preserves_reference_glyphs():
    selected = glyphs.glyphs_for("unicode")

    assert selected.tree == "├ "
    assert selected.pointer == "❯ "
    assert selected.ellipsis == "…"
    assert selected.fold_closed == "▸"
    assert selected.check == "☒"
    assert selected.block_full == "█"


def test_auto_mode_uses_utf8_capabilities(monkeypatch):
    monkeypatch.setattr(glyphs.sys, "stdout", SimpleNamespace(encoding="UTF-8"))
    monkeypatch.setattr(glyphs.sys, "stderr", SimpleNamespace(encoding="UTF-8"))
    monkeypatch.setattr(locale, "getpreferredencoding", lambda _False=False: "UTF-8")

    assert glyphs.unicode_supported() is True
    assert glyphs.glyphs_for("auto") == glyphs.UNICODE_GLYPHS


def test_auto_mode_falls_back_when_terminal_encoding_is_not_utf8(monkeypatch):
    monkeypatch.setattr(glyphs.sys, "stdout", SimpleNamespace(encoding="US-ASCII"))
    monkeypatch.setattr(glyphs.sys, "stderr", SimpleNamespace(encoding="US-ASCII"))
    monkeypatch.setattr(locale, "getpreferredencoding", lambda _False=False: "US-ASCII")

    assert glyphs.unicode_supported() is False
    assert glyphs.glyphs_for("auto") == glyphs.ASCII_GLYPHS


def test_configure_and_reset_are_deterministic():
    configured = glyphs.configure_glyphs("ascii")
    assert glyphs.current_glyphs() is configured

    glyphs.reset_glyphs()
    assert glyphs.current_glyphs() in {glyphs.ASCII_GLYPHS, glyphs.UNICODE_GLYPHS}
