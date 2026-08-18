from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .web_models import FetchPageArgs, FetchedPageResult
from .web_provider import WebSearchError, WebSearchTimeout
from .web_sanitizer import WebSanitizer


class SSRFBlocked(WebSearchError):
    """Raised when a URL resolves to a local or private network address."""


class PageContentRejected(WebSearchError):
    """Raised when the response is not an allowed textual page."""


class FetchPageService:
    """Bounded page fetcher with fail-closed SSRF and redirect checks."""

    user_agent = "termux-coder/1.x (safe page fetch)"
    allowed_content_types = {"text/html", "application/xhtml+xml", "text/plain"}

    def __init__(
        self,
        *,
        timeout_s: float = 10.0,
        max_response_bytes: int = 500_000,
        max_redirects: int = 4,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if max_response_bytes < 1024:
            raise ValueError("max_response_bytes must be at least 1024")
        if not 0 <= max_redirects <= 5:
            raise ValueError("max_redirects must be between 0 and 5")
        self.timeout_s = timeout_s
        self.max_response_bytes = max_response_bytes
        self.max_redirects = max_redirects

    @staticmethod
    async def _resolve_public(hostname: str, port: int | None) -> None:
        host = hostname.rstrip(".").lower()
        if host in {"localhost", "localhost.localdomain", "ip6-localhost"}:
            raise SSRFBlocked(f"local hostname is blocked: {hostname}")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            if not literal.is_global:
                raise SSRFBlocked(f"non-public IP address is blocked: {hostname}")
            return

        try:
            infos = await asyncio.to_thread(
                socket.getaddrinfo,
                host,
                port or 443,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise SSRFBlocked(f"hostname could not be resolved safely: {hostname}") from exc
        addresses = {info[4][0] for info in infos if info[4]}
        if not addresses:
            raise SSRFBlocked(f"hostname returned no addresses: {hostname}")
        for address in addresses:
            try:
                parsed = ipaddress.ip_address(address)
            except ValueError as exc:
                raise SSRFBlocked(f"invalid resolved address for {hostname}") from exc
            if not parsed.is_global:
                raise SSRFBlocked(f"hostname resolves to a non-public address: {hostname}")

    @classmethod
    async def _validate_url(cls, url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise SSRFBlocked("only public http(s) URLs are allowed")
        if parsed.username is not None or parsed.password is not None:
            raise SSRFBlocked("URLs with credentials are blocked")
        try:
            port = parsed.port
        except ValueError as exc:
            raise SSRFBlocked("URL contains an invalid port") from exc
        await cls._resolve_public(parsed.hostname, port)
        return url

    async def _read_bounded(self, response: httpx.Response) -> tuple[bytes, bool]:
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self.max_response_bytes:
            raise PageContentRejected("page exceeds maximum response size")
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

    async def _request(self, url: str) -> tuple[str, bytes, str, list[str], bool]:
        redirect_chain: list[str] = []
        current = url
        timeout = httpx.Timeout(self.timeout_s)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": self.user_agent, "Accept": "text/html,text/plain;q=0.9"},
        ) as client:
            for redirect_count in range(self.max_redirects + 1):
                current = await self._validate_url(current)
                async with client.stream("GET", current) as response:
                    if 300 <= response.status_code < 400:
                        location = response.headers.get("location")
                        if not location or redirect_count >= self.max_redirects:
                            raise PageContentRejected("redirect limit exceeded or location missing")
                        redirect_chain.append(current)
                        current = urljoin(current, location)
                        continue
                    if response.status_code >= 400:
                        raise WebSearchError(f"page returned HTTP {response.status_code}")
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type not in self.allowed_content_types:
                        raise PageContentRejected(
                            f"content type is not allowed: {content_type or 'unknown'}"
                        )
                    body, truncated = await self._read_bounded(response)
                    return current, body, content_type, redirect_chain, truncated
        raise PageContentRejected("page request did not produce a response")

    async def fetch(self, args: FetchPageArgs) -> FetchedPageResult:
        try:
            current, body, content_type, redirects, truncated = await asyncio.wait_for(
                self._request(args.url), timeout=self.timeout_s
            )
        except asyncio.TimeoutError as exc:
            raise WebSearchTimeout(f"page fetch timed out after {self.timeout_s}s") from exc

        raw = body.decode("utf-8", errors="replace")
        title = ""
        if content_type in {"text/html", "application/xhtml+xml"}:
            soup = BeautifulSoup(raw, "html.parser")
            title_node = soup.find("title")
            title = WebSanitizer.sanitize(
                title_node.get_text(" ", strip=True) if title_node else "",
                max_chars=500,
            ).text
        sanitized = WebSanitizer.sanitize(raw, max_chars=args.max_chars)
        return FetchedPageResult(
            url=args.url,
            final_url=current,
            title=title,
            content=sanitized.text,
            content_type=content_type,
            content_hash=hashlib.sha256(sanitized.text.encode("utf-8")).hexdigest(),
            redirect_chain=redirects,
            truncated=truncated or sanitized.truncated,
            possible_prompt_injection=sanitized.possible_prompt_injection,
        )


async def fetch_page(args: FetchPageArgs, ctx) -> str:
    """Fetch a bounded public page as untrusted, read-only data."""
    if not getattr(ctx.settings, "web_search_enabled", True):
        return "page fetch is disabled by configuration"
    policy = ctx.policy_engine.evaluate_tool("fetch_page")
    if not policy.allowed:
        return f"page fetch denied: {policy.reason}"
    if policy.requires_approval and not getattr(ctx, "orchestrator_approval_granted", False):
        approved = await ctx.ui.request_approval(
            "network",
            {
                "title": "Approve page fetch?",
                "url": args.url,
                "provider": "direct-page",
            },
        )
        ctx.audit.log("fetch_page_approval", url=args.url, approved=approved)
        if not approved:
            return "user rejected page fetch"

    await ctx.ui.on_event("fetch_page_started", url=args.url)
    service = FetchPageService(
        timeout_s=float(getattr(ctx.settings, "web_search_timeout_s", 10.0)),
        max_response_bytes=int(
            getattr(ctx.settings, "web_search_max_response_bytes", 500_000)
        ),
    )
    try:
        result = await service.fetch(args)
    except (SSRFBlocked, PageContentRejected, WebSearchTimeout, WebSearchError) as exc:
        ctx.audit.log("fetch_page_failed", url=args.url, error=str(exc))
        await ctx.ui.on_event("fetch_page_failed", url=args.url, error=str(exc))
        return f"page fetch error: {exc}"

    ctx.audit.log(
        "fetch_page_finished",
        url=result.url,
        final_url=result.final_url,
        content_type=result.content_type,
        truncated=result.truncated,
        content_hash=result.content_hash[:16],
    )
    await ctx.ui.on_event(
        "fetch_page_finished",
        url=result.final_url,
        truncated=result.truncated,
    )
    return result.model_dump_json()


__all__ = ["FetchPageService", "PageContentRejected", "SSRFBlocked", "fetch_page"]
