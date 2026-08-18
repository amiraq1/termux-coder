from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from .web_models import WebSearchArgs, WebSearchResult
from .web_provider import (
    ProviderUnavailable,
    WebSearchError,
    WebSearchProvider,
    WebSearchTimeout,
)


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    provider: str
    consecutive_failures: int
    circuit_open: bool
    cooldown_remaining_s: float
    cache_entries: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": "degraded" if self.circuit_open else "healthy",
            "consecutive_failures": self.consecutive_failures,
            "circuit_open": self.circuit_open,
            "cooldown_remaining_s": round(self.cooldown_remaining_s, 3),
            "cache_entries": self.cache_entries,
        }


class ResilientWebSearchProvider(WebSearchProvider):
    """Bounded resilience wrapper for a read-only web search provider.

    The wrapper never executes commands or changes policy decisions. It only
    controls repeated network reads, short-lived caching, and fail-fast
    behavior after repeated transient failures.
    """

    name = "resilient-search"

    def __init__(
        self,
        provider: WebSearchProvider,
        *,
        max_retries: int = 2,
        base_delay_s: float = 0.25,
        failure_threshold: int = 3,
        cooldown_s: float = 60.0,
        cache_ttl_s: float = 30.0,
        max_cache_entries: int = 32,
    ) -> None:
        if max_retries < 0 or max_retries > 5:
            raise ValueError("max_retries must be between 0 and 5")
        if base_delay_s < 0 or base_delay_s > 10:
            raise ValueError("base_delay_s must be between 0 and 10")
        if failure_threshold < 1 or failure_threshold > 10:
            raise ValueError("failure_threshold must be between 1 and 10")
        if cooldown_s <= 0 or cooldown_s > 3600:
            raise ValueError("cooldown_s must be between 0 and 3600")
        if cache_ttl_s < 0 or cache_ttl_s > 3600:
            raise ValueError("cache_ttl_s must be between 0 and 3600")
        if max_cache_entries < 1 or max_cache_entries > 256:
            raise ValueError("max_cache_entries must be between 1 and 256")
        self.provider = provider
        self.max_retries = max_retries
        self.base_delay_s = base_delay_s
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self.cache_ttl_s = cache_ttl_s
        self.max_cache_entries = max_cache_entries
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._cache: dict[tuple[str, int, str], tuple[float, WebSearchResult]] = {}
        self._state_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return f"resilient-{self.provider.name}"

    @staticmethod
    def _cache_key(args: WebSearchArgs) -> tuple[str, int, str]:
        return (args.query, args.max_results, args.region)

    @staticmethod
    def _is_transient(exc: BaseException) -> bool:
        if isinstance(exc, (WebSearchTimeout, asyncio.TimeoutError)):
            return True
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "timeout",
                "timed out",
                "temporar",
                "connection",
                "connect",
                "reset",
                "dns",
                "rate limit",
                "http 429",
                "http 500",
                "http 502",
                "http 503",
                "http 504",
            )
        )

    async def _cached(self, key: tuple[str, int, str]) -> WebSearchResult | None:
        if self.cache_ttl_s <= 0:
            return None
        now = time.monotonic()
        async with self._state_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            expires_at, result = entry
            if expires_at <= now:
                self._cache.pop(key, None)
                return None
            return result.model_copy(deep=True)

    async def _circuit_is_open(self) -> bool:
        async with self._state_lock:
            return self._circuit_open_until > time.monotonic()

    async def _record_success(self, key: tuple[str, int, str], result: WebSearchResult) -> None:
        async with self._state_lock:
            self._consecutive_failures = 0
            self._circuit_open_until = 0.0
            if self.cache_ttl_s > 0:
                self._cache[key] = (time.monotonic() + self.cache_ttl_s, result.model_copy(deep=True))
                while len(self._cache) > self.max_cache_entries:
                    oldest_key = min(self._cache, key=lambda item: self._cache[item][0])
                    self._cache.pop(oldest_key, None)

    async def _record_transient_failure(self) -> None:
        async with self._state_lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.failure_threshold:
                self._circuit_open_until = time.monotonic() + self.cooldown_s

    def health(self) -> ProviderHealth:
        remaining = max(0.0, self._circuit_open_until - time.monotonic())
        return ProviderHealth(
            provider=self.provider.name,
            consecutive_failures=self._consecutive_failures,
            circuit_open=remaining > 0,
            cooldown_remaining_s=remaining,
            cache_entries=len(self._cache),
        )

    def configuration(self) -> dict[str, Any]:
        """Return non-sensitive resilience settings for local diagnostics."""
        return {
            "max_retries": self.max_retries,
            "base_delay_s": self.base_delay_s,
            "failure_threshold": self.failure_threshold,
            "cooldown_s": self.cooldown_s,
            "cache_ttl_s": self.cache_ttl_s,
            "max_cache_entries": self.max_cache_entries,
        }

    async def search(self, args: WebSearchArgs) -> WebSearchResult:
        key = self._cache_key(args)
        cached = await self._cached(key)
        if cached is not None:
            return cached
        if await self._circuit_is_open():
            raise ProviderUnavailable(
                f"provider circuit is open: {self.provider.name}"
            )

        attempts = self.max_retries + 1
        last_error: BaseException | None = None
        for attempt in range(attempts):
            try:
                result = await self.provider.search(args)
                await self._record_success(key, result)
                return result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                transient = self._is_transient(exc)
                if not transient:
                    raise
                if attempt + 1 >= attempts:
                    await self._record_transient_failure()
                    break
                delay = self.base_delay_s * (2**attempt)
                if delay > 0:
                    await asyncio.sleep(delay)

        if last_error is not None:
            raise last_error
        raise WebSearchError("provider failed without an exception")


__all__ = ["ProviderHealth", "ResilientWebSearchProvider"]
