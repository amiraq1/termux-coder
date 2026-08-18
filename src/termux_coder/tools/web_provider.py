from __future__ import annotations

from typing import Protocol, runtime_checkable

from .web_models import WebSearchArgs, WebSearchResult


class WebSearchError(Exception):
    """Base error for provider-level search failures."""


class WebSearchTimeout(WebSearchError):
    """Raised when a provider exceeds its configured timeout."""


@runtime_checkable
class WebSearchProvider(Protocol):
    """Async provider contract; implementations must not execute shell commands."""

    name: str

    async def search(self, args: WebSearchArgs) -> WebSearchResult:
        """Return bounded, sanitized, untrusted search data."""
        ...


class ProviderUnavailable(WebSearchError):
    """Raised when no network provider has been configured."""


class UnconfiguredWebSearchProvider:
    """Fail-closed provider used until P1 enables a concrete network backend."""

    name = "unconfigured"

    async def search(self, args: WebSearchArgs) -> WebSearchResult:
        raise ProviderUnavailable(
            "web search provider is not configured; enable a provider in P1"
        )


__all__ = [
    "ProviderUnavailable",
    "UnconfiguredWebSearchProvider",
    "WebSearchError",
    "WebSearchProvider",
    "WebSearchTimeout",
]
