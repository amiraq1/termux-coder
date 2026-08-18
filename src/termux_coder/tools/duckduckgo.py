from __future__ import annotations

import asyncio
import time
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .web_models import SearchResultItem, WebSearchArgs, WebSearchResult
from .web_provider import WebSearchError, WebSearchProvider, WebSearchTimeout
from .web_sanitizer import WebSanitizer


class DuckDuckGoProvider(WebSearchProvider):
    """Small, bounded DuckDuckGo HTML provider for Termux."""

    name = "duckduckgo"
    endpoint = "https://html.duckduckgo.com/html/"
    user_agent = "termux-coder/1.x (safe web search)"

    def __init__(
        self,
        *,
        timeout_s: float = 10.0,
        max_response_bytes: int = 500_000,
        max_results: int = 5,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if max_response_bytes < 1024:
            raise ValueError("max_response_bytes must be at least 1024")
        self.timeout_s = timeout_s
        self.max_response_bytes = max_response_bytes
        self.max_results = max(1, min(max_results, 10))

    async def _read_bounded(self, response: httpx.Response) -> tuple[bytes, bool]:
        chunks: list[bytes] = []
        size = 0
        truncated = False
        async for chunk in response.aiter_bytes():
            if size < self.max_response_bytes:
                keep = chunk[: self.max_response_bytes - size]
                chunks.append(keep)
                size += len(keep)
                if len(keep) < len(chunk):
                    truncated = True
            else:
                truncated = True
        return b"".join(chunks), truncated

    @staticmethod
    def _result_url(href: str) -> str:
        value = urljoin("https://html.duckduckgo.com", href.strip())
        parsed = urlsplit(value)
        if parsed.path == "/l/":
            target = parse_qs(parsed.query).get("uddg", [""])[0]
            if target:
                value = unquote(target)
        return value

    def _parse(self, body: bytes, args: WebSearchArgs, truncated: bool, elapsed_ms: int) -> WebSearchResult:
        soup = BeautifulSoup(body, "html.parser")
        items: list[SearchResultItem] = []
        for node in soup.select(".result"):
            link = node.select_one("a.result__a")
            if link is None:
                continue
            title = WebSanitizer.sanitize(link.get_text(" ", strip=True), max_chars=500)
            snippet_node = node.select_one(".result__snippet")
            snippet = WebSanitizer.sanitize(
                snippet_node.get_text(" ", strip=True) if snippet_node else "",
                max_chars=1200,
            )
            try:
                items.append(
                    SearchResultItem(
                        title=title.text or "Untitled result",
                        url=self._result_url(str(link.get("href", ""))),
                        snippet=snippet.text,
                        source=self.name,
                        possible_prompt_injection=(
                            title.possible_prompt_injection
                            or snippet.possible_prompt_injection
                        ),
                    )
                )
            except ValueError:
                # A malformed provider result is data loss, not a reason to fail
                # the entire search operation.
                continue
            if len(items) >= min(args.max_results, self.max_results):
                break
        return WebSearchResult(
            query=args.query,
            results=items,
            total_found=len(items),
            search_time_ms=elapsed_ms,
            provider=self.name,
            truncated=truncated,
        )

    async def _request(self, args: WebSearchArgs) -> tuple[bytes, bool]:
        timeout = httpx.Timeout(self.timeout_s)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": self.user_agent, "Accept": "text/html"},
        ) as client:
            async with client.stream(
                "GET",
                self.endpoint,
                params={"q": args.query, "kl": args.region},
            ) as response:
                if response.status_code >= 400:
                    raise WebSearchError(
                        f"DuckDuckGo returned HTTP {response.status_code}"
                    )
                return await self._read_bounded(response)

    async def search(self, args: WebSearchArgs) -> WebSearchResult:
        started = time.monotonic()
        try:
            body, truncated = await asyncio.wait_for(
                self._request(args), timeout=self.timeout_s
            )
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return self._parse(body, args, truncated, elapsed_ms)
        except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
            raise WebSearchTimeout(
                f"DuckDuckGo search timed out after {self.timeout_s}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise WebSearchError(f"DuckDuckGo request failed: {exc}") from exc


__all__ = ["DuckDuckGoProvider"]
