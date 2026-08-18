from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from .web_models import SearchResultItem, WebSearchArgs, WebSearchResult
from .web_provider import WebSearchProvider


DEFAULT_OFFICIAL_DOCS_DOMAINS = (
    "docs.python.org",
    "python.org",
    "pydantic.dev",
    "fastapi.tiangolo.com",
    "docs.pytest.org",
    "docs.djangoproject.com",
    "numpy.org",
    "pandas.pydata.org",
    "docs.scipy.org",
    "nodejs.org",
    "typescriptlang.org",
    "react.dev",
    "nextjs.org",
    "docs.docker.com",
    "kubernetes.io",
    "docs.github.com",
)


def _normalize_domain(value: str) -> str:
    value = value.strip().lower().rstrip(".")
    if not value or "/" in value or ":" in value or "@" in value:
        raise ValueError(f"invalid official documentation domain: {value!r}")
    return value


class OfficialDocsProvider(WebSearchProvider):
    """Read-only search adapter that keeps only allowlisted official docs."""

    name = "official_docs"

    def __init__(
        self,
        search_provider: WebSearchProvider,
        *,
        allowed_domains: Iterable[str] = DEFAULT_OFFICIAL_DOCS_DOMAINS,
    ) -> None:
        domains = tuple(dict.fromkeys(_normalize_domain(item) for item in allowed_domains))
        if not domains:
            raise ValueError("at least one official documentation domain is required")
        self.search_provider = search_provider
        self.allowed_domains = frozenset(domains)

    def _is_allowed_url(self, url: str) -> bool:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"http", "https"} or not hostname:
            return False
        return any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in self.allowed_domains
        )

    def _filter_result(self, item: SearchResultItem) -> SearchResultItem | None:
        if not self._is_allowed_url(item.url):
            return None
        return item.model_copy(update={"source": self.name})

    async def search(self, args: WebSearchArgs) -> WebSearchResult:
        """Search the configured provider, then fail closed on non-official URLs."""
        result = await self.search_provider.search(args)
        official_results = [
            filtered
            for item in result.results
            if (filtered := self._filter_result(item)) is not None
        ][: args.max_results]
        return result.model_copy(
            update={
                "results": official_results,
                "total_found": len(official_results),
                "provider": self.name,
            }
        )


__all__ = ["DEFAULT_OFFICIAL_DOCS_DOMAINS", "OfficialDocsProvider"]
