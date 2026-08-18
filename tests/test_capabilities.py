import asyncio
from types import SimpleNamespace

from termux_coder.core.capabilities import (
    CapabilityDescriptor,
    CapabilityRegistry,
    WebSearchCapabilityAdapter,
)
from termux_coder.tools.web_models import SearchResultItem, WebSearchArgs, WebSearchResult


class FakeProvider:
    name = "fake-search"

    def __init__(self):
        self.calls = []

    async def search(self, args):
        self.calls.append(args)
        return WebSearchResult(
            query=args.query,
            provider=self.name,
            results=[
                SearchResultItem(
                    title="Official docs",
                    url="https://example.com/docs",
                    snippet="bounded result",
                )
            ],
            total_found=1,
        )


def test_web_search_adapter_preserves_provider_contract():
    provider = FakeProvider()
    adapter = WebSearchCapabilityAdapter(provider)

    result = asyncio.run(adapter.search(WebSearchArgs(query="python")))

    assert result.provider == "fake-search"
    assert provider.calls[0].query == "python"
    assert adapter.descriptor == CapabilityDescriptor(
        key="web_search",
        provider="fake-search",
        kind="network_search",
        permission="network",
        read_only=True,
        description="Bounded public web search returning untrusted data",
    )


def test_registry_requires_explicit_unique_registration():
    registry = CapabilityRegistry()
    first = WebSearchCapabilityAdapter(FakeProvider())
    registry.register(first)

    assert registry.keys() == ("web_search",)
    assert registry.get("web_search") is first
    assert registry.descriptors() == (first.descriptor,)

    try:
        registry.register(WebSearchCapabilityAdapter(FakeProvider()))
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("duplicate capability registration must fail")


def test_registry_does_not_discover_unknown_capabilities():
    registry = CapabilityRegistry()
    assert registry.get("github") is None
    try:
        registry.require("github")
    except KeyError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("unknown capability must fail closed")


def test_legacy_flag_can_disable_adapter_selection(monkeypatch):
    from termux_coder.tools import web_search

    settings = SimpleNamespace(
        capability_adapters_enabled=False,
        web_search_provider="duckduckgo",
        web_search_timeout_s=1.0,
        web_search_max_response_bytes=1024,
        web_search_max_results=1,
    )
    legacy = object()
    monkeypatch.setattr(web_search, "DuckDuckGoProvider", lambda **_kwargs: legacy)
    ctx = SimpleNamespace(settings=settings, capability_registry=CapabilityRegistry())

    assert web_search._provider(ctx) is legacy


def test_enabled_flag_selects_registered_adapter(monkeypatch):
    from termux_coder.tools import web_search

    provider = FakeProvider()
    adapter = WebSearchCapabilityAdapter(provider)
    registry = CapabilityRegistry()
    registry.register(adapter)
    settings = SimpleNamespace(
        capability_adapters_enabled=True,
        web_search_provider="duckduckgo",
        web_search_timeout_s=1.0,
        web_search_max_response_bytes=1024,
        web_search_max_results=1,
    )
    monkeypatch.setattr(
        web_search,
        "DuckDuckGoProvider",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("legacy provider must not be created")),
    )
    ctx = SimpleNamespace(settings=settings, capability_registry=registry)

    assert web_search._provider(ctx) is adapter



def test_official_docs_provider_filters_to_allowlisted_domains():
    from termux_coder.tools.official_docs import OfficialDocsProvider

    class SearchProvider:
        name = "fake-search"

        async def search(self, args):
            return WebSearchResult(
                query=args.query,
                provider=self.name,
                results=[
                    SearchResultItem(title="Python", url="https://docs.python.org/3/"),
                    SearchResultItem(title="Subdomain", url="https://dev.docs.python.org/page"),
                    SearchResultItem(title="Evil", url="https://docs.python.org.evil.test/"),
                    SearchResultItem(title="Blog", url="https://example.com/blog"),
                ],
                total_found=4,
            )

    provider = OfficialDocsProvider(
        SearchProvider(), allowed_domains=("docs.python.org",)
    )
    result = asyncio.run(provider.search(WebSearchArgs(query="python", max_results=5)))

    assert result.provider == "official_docs"
    assert [item.title for item in result.results] == ["Python", "Subdomain"]
    assert all(item.source == "official_docs" for item in result.results)
    assert result.total_found == 2


def test_official_docs_provider_rejects_empty_allowlist():
    from termux_coder.tools.official_docs import OfficialDocsProvider

    try:
        OfficialDocsProvider(FakeProvider(), allowed_domains=())
    except ValueError as exc:
        assert "at least one" in str(exc)
    else:
        raise AssertionError("empty official docs allowlist must fail closed")


def test_official_docs_provider_rejects_invalid_domain_config():
    from termux_coder.tools.official_docs import OfficialDocsProvider

    try:
        OfficialDocsProvider(FakeProvider(), allowed_domains=("https://docs.python.org",))
    except ValueError as exc:
        assert "invalid official documentation domain" in str(exc)
    else:
        raise AssertionError("domain config must not accept URL syntax")
