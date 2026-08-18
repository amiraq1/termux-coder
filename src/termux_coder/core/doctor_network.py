from __future__ import annotations

import asyncio
import time
from typing import Any

from ..security.scrubber import scrub
from ..tools.web_models import WebSearchArgs
from ..tools.web_provider import ProviderUnavailable, WebSearchError, WebSearchProvider


class LiveNetworkProbe:
    """Perform one bounded, read-only provider probe for Doctor."""

    def __init__(
        self,
        provider: WebSearchProvider,
        *,
        timeout_s: float = 10.0,
        query: str = "Python official documentation",
    ) -> None:
        if timeout_s <= 0 or timeout_s > 30:
            raise ValueError("network probe timeout must be greater than 0 and at most 30 seconds")
        self.provider = provider
        self.timeout_s = timeout_s
        self.query = WebSearchArgs(query=query).query

    def run(self) -> tuple[str, str, dict[str, Any]]:
        started = time.monotonic()
        args = WebSearchArgs(
            query=self.query,
            max_results=1,
            region="wt-wt",
        )

        async def execute() -> Any:
            return await asyncio.wait_for(self.provider.search(args), timeout=self.timeout_s)

        try:
            result = asyncio.run(execute())
        except asyncio.TimeoutError:
            duration_ms = int((time.monotonic() - started) * 1000)
            return (
                "timeout",
                f"live network probe timed out after {self.timeout_s:g}s",
                {"duration_ms": duration_ms, "provider": self.provider.name},
            )
        except ProviderUnavailable as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return (
                "warning",
                "provider is unavailable or its circuit is open",
                {"duration_ms": duration_ms, "provider": self.provider.name, "error": scrub(str(exc))},
            )
        except WebSearchError as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return (
                "error",
                "live network probe failed",
                {"duration_ms": duration_ms, "provider": self.provider.name, "error": scrub(str(exc))},
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return (
                "error",
                "live network probe failed unexpectedly",
                {"duration_ms": duration_ms, "provider": self.provider.name, "error": scrub(str(exc))},
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        result_count = len(result.results)
        status = "ok" if result_count else "warning"
        message = "live network probe succeeded" if result_count else "provider responded with no results"
        return status, message, {
            "duration_ms": duration_ms,
            "provider": result.provider,
            "result_count": result_count,
            "search_time_ms": result.search_time_ms,
            "truncated": result.truncated,
        }


__all__ = ["LiveNetworkProbe"]
