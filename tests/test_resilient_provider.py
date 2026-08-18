import asyncio

import pytest

from termux_coder.tools.resilient_provider import ResilientWebSearchProvider
from termux_coder.tools.web_models import WebSearchArgs, WebSearchResult
from termux_coder.tools.web_provider import (
    ProviderUnavailable,
    WebSearchError,
    WebSearchTimeout,
)


class FakeProvider:
    name = "fake"

    def __init__(self, failures=None):
        self.failures = list(failures or [])
        self.calls = 0

    async def search(self, args):
        self.calls += 1
        if self.failures:
            failure = self.failures.pop(0)
            raise failure
        return WebSearchResult(query=args.query, provider=self.name, total_found=0)


def test_retry_recovers_from_transient_timeout():
    provider = FakeProvider([WebSearchTimeout("timed out"), WebSearchTimeout("timed out")])
    resilient = ResilientWebSearchProvider(
        provider, max_retries=2, base_delay_s=0, cache_ttl_s=0
    )

    result = asyncio.run(resilient.search(WebSearchArgs(query="python")))

    assert result.provider == "fake"
    assert provider.calls == 3
    assert resilient.health().consecutive_failures == 0


def test_success_is_cached_with_bounded_key():
    provider = FakeProvider()
    resilient = ResilientWebSearchProvider(
        provider, max_retries=0, cache_ttl_s=60, max_cache_entries=2
    )
    args = WebSearchArgs(query="python")

    asyncio.run(resilient.search(args))
    asyncio.run(resilient.search(args))

    assert provider.calls == 1
    assert resilient.health().cache_entries == 1


def test_circuit_opens_after_repeated_transient_failures():
    provider = FakeProvider(
        [WebSearchTimeout("timed out"), WebSearchTimeout("timed out")]
    )
    resilient = ResilientWebSearchProvider(
        provider,
        max_retries=0,
        failure_threshold=2,
        cooldown_s=60,
        cache_ttl_s=0,
    )
    args = WebSearchArgs(query="python")

    with pytest.raises(WebSearchTimeout):
        asyncio.run(resilient.search(args))
    with pytest.raises(WebSearchTimeout):
        asyncio.run(resilient.search(args))
    with pytest.raises(ProviderUnavailable, match="circuit is open"):
        asyncio.run(resilient.search(args))

    health = resilient.health()
    assert health.circuit_open is True
    assert health.consecutive_failures == 2
    assert provider.calls == 2


def test_non_transient_errors_are_not_retried():
    provider = FakeProvider([WebSearchError("invalid query")])
    resilient = ResilientWebSearchProvider(provider, max_retries=3, base_delay_s=0)

    with pytest.raises(WebSearchError, match="invalid query"):
        asyncio.run(resilient.search(WebSearchArgs(query="python")))

    assert provider.calls == 1
