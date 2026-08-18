from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from termux_coder.security.audit import AuditLog
from termux_coder.security.policy import PolicyEngine
from termux_coder.tools import web_search as search_tool
from termux_coder.tools.duckduckgo import DuckDuckGoProvider
from termux_coder.tools.web_models import WebSearchArgs
from termux_coder.tools.web_provider import WebSearchTimeout


class _Settings:
    web_search_enabled = True
    web_search_provider = "duckduckgo"
    web_search_timeout_s = 3.0
    web_search_max_response_bytes = 500_000
    web_search_max_results = 5


class _UI:
    def __init__(self, approve: bool = True):
        self.approve = approve
        self.approvals = []
        self.events = []

    async def request_approval(self, kind, payload):
        self.approvals.append((kind, payload))
        return self.approve

    async def on_event(self, kind, **payload):
        self.events.append((kind, payload))


class _Audit:
    def __init__(self, root: Path):
        self._audit = AuditLog(root / "audit.jsonl")

    def log(self, *args, **kwargs):
        return self._audit.log(*args, **kwargs)


class _Response:
    def __init__(self, body: bytes, status_code: int = 200):
        self.body = body
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def aiter_bytes(self):
        yield self.body


class _Client:
    def __init__(self, response: _Response):
        self.response = response
        self.request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def stream(self, method, url, **kwargs):
        self.request = (method, url, kwargs)
        return self.response


def _html() -> bytes:
    return b"""
    <html><body>
      <div class='result'>
        <a class='result__a' href='//example.com/docs'>Example Docs</a>
        <a class='result__snippet'>Useful <b>documentation</b>.</a>
      </div>
      <div class='result'>
        <a class='result__a' href='https://example.org'>Second</a>
        <a class='result__snippet'>Second result.</a>
      </div>
    </body></html>
    """


def test_network_policy_modes():
    ask = PolicyEngine("ASK").evaluate_tool("web_search")
    auto = PolicyEngine("AUTO").evaluate_tool("web_search")
    readonly = PolicyEngine("READONLY").evaluate_tool("web_search")

    assert ask.allowed and ask.requires_approval
    assert auto.allowed and not auto.requires_approval
    assert readonly.allowed and not readonly.requires_approval


def test_duckduckgo_provider_parses_bounded_results(monkeypatch):
    client = _Client(_Response(_html()))
    monkeypatch.setattr(
        "termux_coder.tools.duckduckgo.httpx.AsyncClient",
        lambda **_kwargs: client,
    )
    provider = DuckDuckGoProvider(max_results=1)

    result = asyncio.run(provider.search(WebSearchArgs(query="python")))

    assert result.provider == "duckduckgo"
    assert len(result.results) == 1
    assert result.results[0].url == "https://example.com/docs"
    assert result.results[0].snippet == "Useful documentation."
    assert client.request[0] == "GET"
    assert client.request[2]["params"]["q"] == "python"


def test_duckduckgo_provider_enforces_total_timeout(monkeypatch):
    provider = DuckDuckGoProvider(timeout_s=0.01)

    async def slow_request(_args):
        await asyncio.sleep(0.1)
        return b"", False

    monkeypatch.setattr(provider, "_request", slow_request)

    with pytest.raises(WebSearchTimeout, match="timed out"):
        asyncio.run(provider.search(WebSearchArgs(query="python")))


def test_duckduckgo_provider_marks_oversized_response(monkeypatch):
    body = b"<html>" + (b"x" * 3000) + b"</html>"
    client = _Client(_Response(body))
    monkeypatch.setattr(
        "termux_coder.tools.duckduckgo.httpx.AsyncClient",
        lambda **_kwargs: client,
    )
    provider = DuckDuckGoProvider(max_response_bytes=1024)

    result = asyncio.run(provider.search(WebSearchArgs(query="python")))

    assert result.truncated is True


def test_web_search_requests_network_approval_in_ask_mode(tmp_path, monkeypatch):
    ui = _UI(approve=False)
    ctx = SimpleNamespace(
        settings=_Settings(),
        policy_engine=PolicyEngine("ASK"),
        ui=ui,
        audit=_Audit(tmp_path),
        orchestrator_approval_granted=False,
    )
    called = False

    class Provider:
        async def search(self, _args):
            nonlocal called
            called = True
            raise AssertionError("provider must not run after rejection")

    monkeypatch.setattr(search_tool, "_provider", lambda _ctx: Provider())

    result = asyncio.run(search_tool.web_search(WebSearchArgs(query="python"), ctx))

    assert result == "user rejected web search"
    assert called is False
    assert ui.approvals[0][0] == "network"


def test_web_search_returns_untrusted_json_in_readonly_mode(tmp_path, monkeypatch):
    ui = _UI()
    ctx = SimpleNamespace(
        settings=_Settings(),
        policy_engine=PolicyEngine("READONLY"),
        ui=ui,
        audit=_Audit(tmp_path),
        orchestrator_approval_granted=False,
    )

    class Provider:
        async def search(self, args):
            from termux_coder.tools.web_models import SearchResultItem, WebSearchResult

            return WebSearchResult(
                query=args.query,
                provider="fake",
                results=[SearchResultItem(title="Example", url="https://example.com")],
                total_found=1,
            )

    monkeypatch.setattr(search_tool, "_provider", lambda _ctx: Provider())

    result = asyncio.run(search_tool.web_search(WebSearchArgs(query="python"), ctx))

    assert '"provider":"fake"' in result
    assert '"untrusted":true' in result
    assert ui.approvals == []
    assert any(kind == "web_search_finished" for kind, _ in ui.events)
