from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|access[_-]?key|access[_-]?token|auth(?:orization)?|bearer|"
    r"password|passwd|pwd|secret|private[_-]?key|cookie|session[_-]?token|refresh[_-]?token)",
    re.IGNORECASE,
)

_TEXT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
        "[OPENAI_KEY_REDACTED]",
    ),
    (
        re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
        "[GITHUB_TOKEN_REDACTED]",
    ),
    (
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "[AWS_ACCESS_KEY_REDACTED]",
    ),
    (
        re.compile(
            r"(Authorization\s*:\s*Bearer\s+)[^\s,;]+",
            re.IGNORECASE,
        ),
        r"\1[BEARER_TOKEN_REDACTED]",
    ),
    (
        re.compile(
            r"(\b(?:api[_-]?key|apikey|access[_-]?token)\s*[=:]\s*[\"']?)[^\s,;\"']+",
            re.IGNORECASE,
        ),
        r"\1[API_SECRET_REDACTED]",
    ),
    (
        re.compile(
            r"(\b(?:password|passwd|pwd)\s*[=:]\s*[\"']?)[^\s,;\"']+",
            re.IGNORECASE,
        ),
        r"\1[PASSWORD_REDACTED]",
    ),
    (
        re.compile(r"(https?://[^:/\s]+:)[^@/\s]+(@)", re.IGNORECASE),
        r"\1[URL_PASSWORD_REDACTED]\2",
    ),
)


class SecretScrubber:
    """Scrub credentials from structured data at the audit persistence boundary."""

    def scrub_text(self, text: str) -> str:
        result = text
        for pattern, replacement in _TEXT_PATTERNS:
            result = pattern.sub(replacement, result)
        return result

    def _scrub_value(self, key: str | None, value: Any) -> Any:
        if isinstance(value, str):
            if key and _SENSITIVE_KEY_RE.search(key):
                return _REDACTED
            return self.scrub_text(value)
        if isinstance(value, Mapping):
            return {
                item_key: self._scrub_value(str(item_key), item_value)
                for item_key, item_value in value.items()
            }
        if isinstance(value, list):
            return [self._scrub_value(None, item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._scrub_value(None, item) for item in value)
        return value

    def scrub(self, data: Any) -> Any:
        """Return a scrubbed copy without mutating the caller's data."""
        return self._scrub_value(None, data)


_DEFAULT_SCRUBBER = SecretScrubber()


def scrub(data: Any) -> Any:
    """Scrub arbitrary audit payloads using the default stateless scrubber."""
    return _DEFAULT_SCRUBBER.scrub(data)


__all__ = ["SecretScrubber", "scrub"]
