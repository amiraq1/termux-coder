from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from termux_coder.core.research import ResearchCoordinator
from termux_coder.models.research import TaskIntent
from termux_coder.tools.web_models import (
    FetchedPageResult,
    SearchResultItem,
    WebSearchArgs,
    WebSearchResult,
)


NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


def search_result():
    return WebSearchResult(
        query="example latest api",
        provider="test",
        results=[
            SearchResultItem(
                title="Community post",
                url="https://blog.example.net/api",
                snippet="community snippet",
            ),
            SearchResultItem(
                title="Official docs",
                url="https://docs.example.com/api",
                snippet="official snippet",
            ),
            SearchResultItem(
                title="Package registry",
                url="https://pypi.org/project/example-lib/",
                snippet="registry snippet",
            ),
            SearchResultItem(
                title="Duplicate docs",
                url="https://docs.example.com/api/",
                snippet="duplicate",
            ),
        ],
        total_found=4,
    )


def intent():
    return TaskIntent(
        task="Update example-lib to the current API",
        requires_current_docs=True,
        search_query="example-lib latest api",
        package_names=["example-lib"],
    )


def page(url="https://docs.example.com/api"):
    return FetchedPageResult(
        url=url,
        final_url=url,
        title="Official docs page",
        content="Use the documented async client.",
        content_type="text/html",
        content_hash="a" * 64,
    )


class FakeProvider:
    name = "test"

    def __init__(self, result):
        self.result = result
        self.calls = []

    async def search(self, args: WebSearchArgs):
        self.calls.append(args)
        return self.result


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def fetch(self, args):
        self.calls.append(args)
        return self.pages[args.url]


def test_rank_results_prefers_official_registry_and_deduplicates():
    coordinator = ResearchCoordinator(FakeProvider(search_result()), max_sources=8)

    ranked = coordinator.rank_results(search_result().results)

    assert [item.url for item in ranked[:3]] == [
        "https://docs.example.com/api",
        "https://pypi.org/project/example-lib/",
        "https://blog.example.net/api",
    ]
    assert len(ranked) == 3


def test_build_packet_from_snippets_requires_more_research():
    coordinator = ResearchCoordinator(FakeProvider(search_result()))

    packet = asyncio.run(coordinator.build_packet(intent(), search_result()))

    assert packet.confidence == "medium"
    assert packet.requires_more_research is True
    assert packet.evidence[0].source_type == "official_docs"
    assert packet.evidence[0].untrusted is True
    assert len(packet.packet_hash) == 64


def test_build_packet_from_fetched_official_page_is_high_confidence():
    provider = FakeProvider(search_result())
    fetched = {"https://docs.example.com/api": page()}
    coordinator = ResearchCoordinator(provider)

    packet = asyncio.run(
        coordinator.build_packet(intent(), search_result(), fetched_pages=fetched)
    )

    assert packet.confidence == "high"
    assert packet.requires_more_research is False
    assert packet.evidence[0].excerpt.startswith("Use the documented")
    assert packet.evidence[0].source_hash == "a" * 64


def test_research_searches_then_fetches_ranked_sources():
    provider = FakeProvider(search_result())
    fetched = {
        "https://docs.example.com/api": page(),
        "https://pypi.org/project/example-lib/": page(
            "https://pypi.org/project/example-lib/"
        ),
    }
    fetcher = FakeFetcher(fetched)
    coordinator = ResearchCoordinator(provider, fetcher, max_sources=2)

    packet = asyncio.run(coordinator.research(intent()))

    assert provider.calls[0].query == "example-lib latest api"
    assert [call.url for call in fetcher.calls] == [
        "https://docs.example.com/api",
        "https://pypi.org/project/example-lib/",
    ]
    assert packet.confidence == "high"
    assert len(packet.evidence) == 2


def test_failed_page_fetch_keeps_search_snippet():
    provider = FakeProvider(search_result())

    class FailingFetcher:
        async def fetch(self, _args):
            raise httpx.ConnectError("network unavailable")

    coordinator = ResearchCoordinator(provider, FailingFetcher(), max_sources=1)
    packet = asyncio.run(coordinator.research(intent()))

    assert len(packet.evidence) == 1
    assert packet.evidence[0].excerpt == "official snippet"
    assert packet.requires_more_research is True



def test_unexpected_page_fetch_error_is_not_suppressed():
    provider = FakeProvider(search_result())

    class FailingFetcher:
        async def fetch(self, _args):
            raise RuntimeError("unexpected parser failure")

    coordinator = ResearchCoordinator(provider, FailingFetcher(), max_sources=1)
    with pytest.raises(RuntimeError, match="unexpected parser failure"):
        asyncio.run(coordinator.research(intent()))
