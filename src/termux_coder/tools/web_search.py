from __future__ import annotations

from typing import Any

from .duckduckgo import DuckDuckGoProvider
from .web_models import WebSearchArgs, WebSearchResult
from .web_provider import (
    ProviderUnavailable,
    WebSearchError,
    WebSearchTimeout,
)


def _provider(ctx) -> Any:
    if getattr(ctx.settings, "capability_adapters_enabled", True):
        registry = getattr(ctx, "capability_registry", None)
        adapter = registry.get("web_search") if registry is not None else None
        if adapter is not None:
            return adapter

    # Legacy fallback: keep the original provider path available for rollback.
    settings = ctx.settings
    name = getattr(settings, "web_search_provider", "duckduckgo").lower()
    if name == "duckduckgo":
        return DuckDuckGoProvider(
            timeout_s=float(getattr(settings, "web_search_timeout_s", 10.0)),
            max_response_bytes=int(
                getattr(settings, "web_search_max_response_bytes", 500_000)
            ),
            max_results=int(getattr(settings, "web_search_max_results", 5)),
        )
    raise ProviderUnavailable(f"unsupported web search provider: {name}")


async def web_search(args: WebSearchArgs, ctx) -> str:
    """Search the public web without writing files or executing shell commands."""
    if not getattr(ctx.settings, "web_search_enabled", True):
        return "web search is disabled by configuration"

    policy = ctx.policy_engine.evaluate_tool("web_search")
    if not policy.allowed:
        return f"web search denied: {policy.reason}"

    if policy.requires_approval and not getattr(ctx, "orchestrator_approval_granted", False):
        approved = await ctx.ui.request_approval(
            "network",
            {
                "title": "Approve web search?",
                "query": args.query,
                "provider": getattr(ctx.settings, "web_search_provider", "duckduckgo"),
            },
        )
        ctx.audit.log("web_search_approval", query=args.query, approved=approved)
        if not approved:
            return "user rejected web search"

    max_results = min(
        args.max_results,
        int(getattr(ctx.settings, "web_search_max_results", args.max_results)),
        10,
    )
    bounded_args = args.model_copy(update={"max_results": max_results})
    await ctx.ui.on_event(
        "web_search_started",
        query=bounded_args.query,
        provider=getattr(ctx.settings, "web_search_provider", "duckduckgo"),
        capability="web_search",
    )
    try:
        result: WebSearchResult = await _provider(ctx).search(bounded_args)
    except WebSearchTimeout as exc:
        ctx.audit.log("web_search_failed", query=args.query, error=str(exc), kind="timeout")
        await ctx.ui.on_event("web_search_failed", query=args.query, error=str(exc))
        return f"web search timeout: {exc}"
    except WebSearchError as exc:
        ctx.audit.log("web_search_failed", query=args.query, error=str(exc), kind="provider")
        await ctx.ui.on_event("web_search_failed", query=args.query, error=str(exc))
        return f"web search error: {exc}"
    except Exception as exc:
        ctx.audit.log("web_search_failed", query=args.query, error=str(exc), kind="unexpected")
        await ctx.ui.on_event("web_search_failed", query=args.query, error="unexpected provider failure")
        return "web search error: unexpected provider failure"

    payload = result.model_dump_json()
    ctx.audit.log(
        "web_search_finished",
        query=result.query,
        provider=result.provider,
        result_count=len(result.results),
        truncated=result.truncated,
        elapsed_ms=result.search_time_ms,
    )
    await ctx.ui.on_event(
        "web_search_finished",
        query=result.query,
        provider=result.provider,
        result_count=len(result.results),
        truncated=result.truncated,
    )
    return payload


__all__ = ["web_search"]
