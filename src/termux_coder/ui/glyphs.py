"""Terminal-safe glyph selection for Termux and other text terminals.

Unicode is selected only when the active output encodings are UTF-8. Users can
force a mode with TUI_UNICODE=unicode|ascii|auto; ASCII mode is deliberately
plain and portable for old fonts, redirected output, and limited terminals.
"""

from __future__ import annotations

import locale
import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Glyphs:
    tree: str
    branch: str
    last_branch: str
    pointer: str
    bullet: str
    ellipsis: str
    separator: str
    divider: str
    down: str
    up: str
    check: str
    unchecked: str
    fold_open: str
    fold_closed: str
    block_full: str
    block_empty: str
    diamond: str
    status_unknown: str
    status_online: str
    status_degraded: str
    status_offline: str
    status_checking: str
    retry: str


UNICODE_GLYPHS = Glyphs(
    tree="├ ",
    branch="├─ ",
    last_branch="└─ ",
    pointer="❯ ",
    bullet="•",
    ellipsis="…",
    separator="·",
    divider="─",
    down="↓",
    up="↑",
    check="☒",
    unchecked="☐",
    fold_open="▾",
    fold_closed="▸",
    block_full="█",
    block_empty="░",
    diamond="◈",
    status_unknown="?",
    status_online="●",
    status_degraded="!",
    status_offline="×",
    status_checking="◌",
    retry="↻",
)

ASCII_GLYPHS = Glyphs(
    tree="| ",
    branch="|-- ",
    last_branch="`-- ",
    pointer="> ",
    bullet="*",
    ellipsis="...",
    separator="|",
    divider="-",
    down="v",
    up="^",
    check="[x]",
    unchecked="[ ]",
    fold_open="v",
    fold_closed=">",
    block_full="#",
    block_empty="-",
    diamond="*",
    status_unknown="?",
    status_online="+",
    status_degraded="!",
    status_offline="x",
    status_checking=".",
    retry="~",
)

_DEFAULT_GLYPHS: Glyphs | None = None


def _encoding_is_utf8(encoding: str | None) -> bool:
    return bool(encoding) and encoding.replace("_", "-").lower() in {
        "utf-8",
        "utf8",
    }


def unicode_supported() -> bool:
    """Return whether stdout and the locale advertise UTF-8 output."""
    encodings = (
        getattr(sys.stdout, "encoding", None),
        getattr(sys.stderr, "encoding", None),
        locale.getpreferredencoding(False),
    )
    return all(_encoding_is_utf8(encoding) for encoding in encodings if encoding)


def _normalize_mode(mode: str | None) -> str:
    value = (mode or os.environ.get("TUI_UNICODE", "auto")).strip().lower()
    if value in {"1", "true", "yes", "on", "unicode", "utf8", "utf-8"}:
        return "unicode"
    if value in {"0", "false", "no", "off", "ascii", "plain"}:
        return "ascii"
    return "auto"


def glyphs_for(mode: str | None = None) -> Glyphs:
    normalized = _normalize_mode(mode)
    if normalized == "unicode" or (normalized == "auto" and unicode_supported()):
        return UNICODE_GLYPHS
    return ASCII_GLYPHS


def configure_glyphs(mode: str | None = None) -> Glyphs:
    """Configure the process-wide rendering set and return it."""
    global _DEFAULT_GLYPHS
    _DEFAULT_GLYPHS = glyphs_for(mode)
    return _DEFAULT_GLYPHS


def current_glyphs() -> Glyphs:
    global _DEFAULT_GLYPHS
    if _DEFAULT_GLYPHS is None:
        _DEFAULT_GLYPHS = glyphs_for()
    return _DEFAULT_GLYPHS


def reset_glyphs() -> None:
    """Reset the process-wide choice; intended for tests."""
    global _DEFAULT_GLYPHS
    _DEFAULT_GLYPHS = None
