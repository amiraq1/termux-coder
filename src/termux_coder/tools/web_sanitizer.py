from __future__ import annotations

import re
from dataclasses import dataclass

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - optional until the web provider is enabled
    BeautifulSoup = None


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.I),
    re.compile(r"system\s+prompt", re.I),
    re.compile(r"you\s+are\s+now\s+(?:a|an)\b", re.I),
    re.compile(r"(?:new|改変)\s+instructions", re.I),
)


@dataclass(frozen=True)
class SanitizedContent:
    text: str
    truncated: bool
    possible_prompt_injection: bool


class WebSanitizer:
    """Convert web markup to bounded data; never treat it as instructions."""

    MAX_CHARS = 1200

    @classmethod
    def sanitize(cls, content: str, *, max_chars: int | None = None) -> SanitizedContent:
        raw = content or ""
        if BeautifulSoup is not None and "<" in raw and ">" in raw:
            soup = BeautifulSoup(raw, "html.parser")
            for element in soup(
                ["script", "style", "iframe", "object", "embed", "noscript"]
            ):
                element.decompose()
            text = soup.get_text(separator=" ", strip=True)
        else:
            text = raw

        text = _CONTROL_CHARS_RE.sub("", text)
        text = re.sub(r"\s+", " ", text).strip()
        injection = any(pattern.search(text) for pattern in _INJECTION_PATTERNS)
        limit = max_chars if max_chars is not None else cls.MAX_CHARS
        if limit < 1:
            raise ValueError("max_chars must be positive")
        truncated = len(text) > limit
        if truncated:
            marker = "... [truncated]"
            if limit <= len(marker):
                text = marker[:limit]
            else:
                text = text[: limit - len(marker)].rstrip() + marker
        return SanitizedContent(
            text=text,
            truncated=truncated,
            possible_prompt_injection=injection,
        )

    @classmethod
    def clean_html(cls, html_content: str) -> str:
        """Compatibility helper returning only sanitized text."""
        return cls.sanitize(html_content).text


__all__ = ["SanitizedContent", "WebSanitizer"]
