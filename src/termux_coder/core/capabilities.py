from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..tools.web_models import WebSearchArgs, WebSearchResult
from ..tools.web_provider import WebSearchProvider


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """Static metadata for an external capability.

    The descriptor is informational and auditable. It never grants a policy
    permission; PolicyEngine remains the only authority for approval decisions.
    """

    key: str
    provider: str
    kind: str
    permission: str
    read_only: bool
    description: str


class CapabilityAdapter(Protocol):
    descriptor: CapabilityDescriptor


class WebSearchCapabilityAdapter:
    """Adapt a WebSearchProvider to the capability registry contract."""

    def __init__(self, provider: WebSearchProvider) -> None:
        self.provider = provider
        self.descriptor = CapabilityDescriptor(
            key="web_search",
            provider=provider.name,
            kind="network_search",
            permission="network",
            read_only=True,
            description="Bounded public web search returning untrusted data",
        )

    @property
    def name(self) -> str:
        return self.provider.name

    async def search(self, args: WebSearchArgs) -> WebSearchResult:
        """Delegate only the read-only search operation to the provider."""
        return await self.provider.search(args)

    def health(self) -> Any | None:
        """Expose optional provider health metadata without granting control."""
        health = getattr(self.provider, "health", None)
        return health() if callable(health) else None


class CapabilityRegistry:
    """Registry for explicitly configured external capabilities.

    Registration is intentionally explicit. Unknown capabilities are not
    discovered dynamically, and this registry does not execute shell commands,
    write files, or bypass PolicyEngine.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, CapabilityAdapter] = {}

    def register(self, adapter: CapabilityAdapter) -> None:
        key = adapter.descriptor.key
        if not key or key in self._adapters:
            raise ValueError(f"capability already registered or invalid: {key!r}")
        self._adapters[key] = adapter

    def get(self, key: str) -> CapabilityAdapter | None:
        return self._adapters.get(key)

    def require(self, key: str) -> CapabilityAdapter:
        adapter = self.get(key)
        if adapter is None:
            raise KeyError(f"capability is not configured: {key}")
        return adapter

    def descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        return tuple(adapter.descriptor for adapter in self._adapters.values())

    def keys(self) -> tuple[str, ...]:
        return tuple(self._adapters)


__all__ = [
    "CapabilityAdapter",
    "CapabilityDescriptor",
    "CapabilityRegistry",
    "WebSearchCapabilityAdapter",
]
