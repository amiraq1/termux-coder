from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from ..security.scrubber import SecretScrubber


@dataclass(frozen=True)
class ClipboardResult:
    ok: bool
    backend: str | None = None
    redacted: bool = False
    reason: str | None = None


_BACKENDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("termux-clipboard-set", ("termux-clipboard-set",)),
    ("xclip", ("xclip", "-selection", "clipboard")),
    ("wl-copy", ("wl-copy",)),
)


def copy_text(text: str, *, timeout: float = 2.0) -> ClipboardResult:
    """Copy scrubbed text using an available clipboard command.

    Commands are selected from a fixed allowlist and invoked without a shell.
    The original or scrubbed text is never included in the result or errors.
    """
    scrubber = SecretScrubber()
    safe_text = scrubber.scrub_text(text)
    redacted = safe_text != text
    if not safe_text:
        return ClipboardResult(False, redacted=redacted, reason="empty text")

    for backend, command in _BACKENDS:
        executable = shutil.which(command[0])
        if not executable:
            continue
        argv = (executable, *command[1:])
        try:
            subprocess.run(
                argv,
                input=safe_text,
                text=True,
                check=True,
                capture_output=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        return ClipboardResult(True, backend=backend, redacted=redacted)
    return ClipboardResult(False, redacted=redacted, reason="clipboard command unavailable")
