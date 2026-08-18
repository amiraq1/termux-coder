from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlsplit

from ..models.research import EvidenceItem, ResearchPacket, SourceType, TaskIntent
from ..tools.web_models import (
    FetchPageArgs,
    FetchedPageResult,
    SearchResultItem,
    WebSearchArgs,
    WebSearchResult,
)
from ..tools.web_provider import WebSearchProvider


class PageFetcher(Protocol):
    async def fetch(self, args: FetchPageArgs) -> FetchedPageResult:
        ...


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ResearchCoordinator:
    """Coordinate bounded search/page reads and build validated evidence packets.

    The coordinator does not approve writes and does not execute tools. Network
    approval remains the responsibility of the caller (normally the
    AgentOrchestrator) before this service is invoked.
    """

    def __init__(
        self,
        search_provider: WebSearchProvider,
        page_fetcher: PageFetcher | None = None,
        *,
        max_sources: int = 8,
        fetch_max_chars: int = 4_000,
    ) -> None:
        if not 1 <= max_sources <= 8:
            raise ValueError("max_sources must be between 1 and 8")
        if not 100 <= fetch_max_chars <= 50_000:
            raise ValueError("fetch_max_chars must be between 100 and 50000")
        self.search_provider = search_provider
        self.page_fetcher = page_fetcher
        self.max_sources = max_sources
        self.fetch_max_chars = fetch_max_chars

    @staticmethod
    def classify_source(url: str) -> SourceType:
        """Classify a URL conservatively; classification is not trust proof."""
        hostname = (urlsplit(url).hostname or "").lower().rstrip(".")
        if (
            hostname.startswith("docs.")
            or hostname.endswith(".readthedocs.io")
            or hostname in {"docs.python.org", "python.org"}
        ):
            return "official_docs"
        if hostname in {"pypi.org", "www.npmjs.com", "crates.io"} or hostname.endswith(
            ".pypi.org"
        ):
            return "package_registry"
        if hostname in {"github.com", "gitlab.com", "bitbucket.org"} or hostname.endswith(
            ".github.com"
        ):
            return "repository"
        return "other"

    @staticmethod
    def _candidate_key(item: SearchResultItem) -> str:
        return item.url.rstrip("/").lower()

    def rank_results(
        self,
        results: Sequence[SearchResultItem],
    ) -> list[SearchResultItem]:
        """Rank official documentation before registries and general results."""
        priority = {
            "official_docs": 0,
            "package_registry": 1,
            "repository": 2,
            "other": 3,
        }
        unique: dict[str, SearchResultItem] = {}
        for item in results:
            unique.setdefault(self._candidate_key(item), item)
        return sorted(
            unique.values(),
            key=lambda item: (priority[self.classify_source(item.url)], item.url),
        )[: self.max_sources]

    @staticmethod
    def _from_search_item(item: SearchResultItem) -> EvidenceItem:
        excerpt = item.snippet.strip() or item.title.strip()
        return EvidenceItem(
            source_url=item.url,
            title=item.title,
            source_type=ResearchCoordinator.classify_source(item.url),
            excerpt=excerpt[:4000],
            retrieved_at=datetime.now(timezone.utc),
            source_hash=_sha256(excerpt),
            possible_prompt_injection=item.possible_prompt_injection,
        )

    @staticmethod
    def _from_page(
        item: SearchResultItem,
        page: FetchedPageResult,
    ) -> EvidenceItem:
        return EvidenceItem(
            source_url=page.final_url,
            title=page.title or item.title,
            source_type=ResearchCoordinator.classify_source(page.final_url),
            excerpt=page.content[:4000],
            retrieved_at=datetime.now(timezone.utc),
            source_hash=page.content_hash,
            possible_prompt_injection=(
                page.possible_prompt_injection or item.possible_prompt_injection
            ),
        )

    @staticmethod
    def _confidence(
        evidence: Sequence[EvidenceItem],
        verified_urls: set[str],
    ) -> str:
        if any(
            item.source_type == "official_docs"
            and item.source_url.rstrip("/").lower() in verified_urls
            for item in evidence
        ):
            return "high"
        if any(item.source_hash for item in evidence):
            return "medium"
        return "low"

    async def build_packet(
        self,
        intent: TaskIntent,
        search_result: WebSearchResult,
        *,
        fetched_pages: dict[str, FetchedPageResult] | None = None,
    ) -> ResearchPacket:
        """Convert existing search/page results into a validated packet."""
        ranked = self.rank_results(search_result.results)
        fetched_pages = fetched_pages or {}
        evidence: list[EvidenceItem] = []
        seen_urls: set[str] = set()
        for item in ranked:
            key = self._candidate_key(item)
            page = fetched_pages.get(item.url) or fetched_pages.get(key)
            candidate = self._from_page(item, page) if page is not None else self._from_search_item(item)
            if candidate.source_url.rstrip("/").lower() in seen_urls:
                continue
            seen_urls.add(candidate.source_url.rstrip("/").lower())
            evidence.append(candidate)
            if len(evidence) >= self.max_sources:
                break

        verified_urls = {
            url.rstrip("/").lower()
            for page in fetched_pages.values()
            for url in (page.final_url, page.url)
        }
        confidence = self._confidence(evidence, verified_urls)
        selected_urls = [item.source_url for item in evidence]
        return ResearchPacket(
            intent_id=intent.intent_id,
            query=search_result.query,
            evidence=evidence,
            selected_urls=selected_urls,
            confidence=confidence,
            requires_more_research=(
                not evidence
                or not any(
                    item.source_type == "official_docs"
                    and item.source_url.rstrip("/").lower() in verified_urls
                    for item in evidence
                )
            ),
        )

    async def research(self, intent: TaskIntent) -> ResearchPacket:
        """Search and optionally fetch ranked sources for a TaskIntent."""
        query = intent.search_query or intent.task[:200]
        search_result = await self.search_provider.search(
            WebSearchArgs(query=query, max_results=self.max_sources)
        )
        ranked = self.rank_results(search_result.results)
        fetched: dict[str, FetchedPageResult] = {}
        if self.page_fetcher is not None:
            for item in ranked:
                try:
                    fetched[item.url] = await self.page_fetcher.fetch(
                        FetchPageArgs(url=item.url, max_chars=self.fetch_max_chars)
                    )
                except Exception:
                    # A failed page is represented by its bounded search snippet;
                    # one unavailable source must not discard the entire packet.
                    continue
        return await self.build_packet(intent, search_result, fetched_pages=fetched)


__all__ = ["PageFetcher", "ResearchCoordinator"]
