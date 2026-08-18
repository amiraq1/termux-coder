from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from termux_coder.security.audit import AuditLog
from termux_coder.security.policy import PolicyEngine
from termux_coder.tools import fetch_page as fetch_tool
from termux_coder.tools.fetch_page import FetchPageService, PageContentRejected, SSRFBlocked
from termux_coder.tools.web_models import FetchPageArgs


class _Response:
    def __init__(self, body: bytes = b"", *, status_code: int = 200, headers=None):
        self.body = body
        self.status_code = status_code
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def aiter_bytes(self):
        yield self.body


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def stream(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)


class _UI:
    def __init__(self, approve=True):
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
        self.log_file = AuditLog(root / "audit.jsonl")

    def log(self, event, **payload):
        return self.log_file.log(event, **payload)


class _Settings:
    web_search_enabled = True
    web_search_timeout_s = 3.0
    web_search_max_response_bytes = 100_000


def test_fetch_args_reject_unsafe_schemes():
    with pytest.raises(Exception):
        FetchPageArgs(url="file:///etc/passwd")
    with pytest.raises(Exception):
        FetchPageArgs(url="https://user:pass@example.com")


def test_ssrf_blocks_local_and_private_addresses():
    with pytest.raises(SSRFBlocked):
        asyncio.run(FetchPageService._resolve_public("127.0.0.1", 443))
    with pytest.raises(SSRFBlocked):
        asyncio.run(FetchPageService._resolve_public("localhost", 443))
    with pytest.raises(SSRFBlocked):
        asyncio.run(FetchPageService._resolve_public("10.0.0.1", 443))


def test_fetch_service_sanitizes_html_and_returns_hash(monkeypatch):
    client = _Client([
        _Response(
            b"<html><head><title>Docs</title></head><body>"
            b"<script>bad()</script><h1>Hello</h1><p>Use async API.</p></body></html>"
        )
    ])
    async def allow_public(_hostname, _port):
        return None

    monkeypatch.setattr(FetchPageService, "_resolve_public", staticmethod(allow_public))
    monkeypatch.setattr(
        "termux_coder.tools.fetch_page.httpx.AsyncClient",
        lambda **_kwargs: client,
    )
    result = asyncio.run(
        FetchPageService(max_response_bytes=100_000).fetch(
            FetchPageArgs(url="https://docs.example.com/api")
        )
    )

    assert result.title == "Docs"
    assert "Use async API." in result.content
    assert "script" not in result.content
    assert len(result.content_hash) == 64
    assert result.untrusted is True
    assert result.final_url == "https://docs.example.com/api"


def test_fetch_service_rejects_non_text_content(monkeypatch):
    async def allow_public(_hostname, _port):
        return None

    monkeypatch.setattr(FetchPageService, "_resolve_public", staticmethod(allow_public))
    client = _Client([
        _Response(b"binary", headers={"content-type": "application/pdf"})
    ])
    monkeypatch.setattr(
        "termux_coder.tools.fetch_page.httpx.AsyncClient",
        lambda **_kwargs: client,
    )

    with pytest.raises(PageContentRejected, match="content type"):
        asyncio.run(
            FetchPageService().fetch(FetchPageArgs(url="https://docs.example.com/file.pdf"))
        )


def test_fetch_service_blocks_private_redirect(monkeypatch):
    async def resolve_public(hostname, _port):
        if hostname == "127.0.0.1":
            raise SSRFBlocked("private redirect")

    monkeypatch.setattr(FetchPageService, "_resolve_public", staticmethod(resolve_public))
    client = _Client([
        _Response(
            status_code=302,
            headers={"location": "http://127.0.0.1/admin"},
        )
    ])
    monkeypatch.setattr(
        "termux_coder.tools.fetch_page.httpx.AsyncClient",
        lambda **_kwargs: client,
    )

    with pytest.raises(SSRFBlocked, match="private redirect"):
        asyncio.run(
            FetchPageService().fetch(FetchPageArgs(url="https://docs.example.com"))
        )


def test_fetch_page_requests_network_approval(tmp_path, monkeypatch):
    ui = _UI(approve=False)
    ctx = SimpleNamespace(
        settings=_Settings(),
        policy_engine=PolicyEngine("ASK"),
        ui=ui,
        audit=_Audit(tmp_path),
        orchestrator_approval_granted=False,
    )
    result = asyncio.run(
        fetch_tool.fetch_page(FetchPageArgs(url="https://docs.example.com"), ctx)
    )

    assert result == "user rejected page fetch"
    assert ui.approvals[0][0] == "network"


def test_orchestrator_enters_researching_for_fetch_page(tmp_path):
    from termux_coder.core.orchestrator import AgentOrchestrator, TurnState
    from termux_coder.core.registry import ToolRegistry
    from termux_coder.models.contracts import ToolResult
    from termux_coder.providers.mock import MockProvider, MockResponse
    from pydantic import BaseModel, ConfigDict

    class Args(BaseModel):
        model_config = ConfigDict(extra="allow")

    class Settings:
        max_output_chars = 1000
        research_auto_enabled = False

    class Ctx:
        settings = Settings()
        orchestrator_approval_granted = False

    events = []

    async def on_event(kind, **payload):
        events.append((kind, payload))

    audit = _Audit(tmp_path)
    registry = ToolRegistry()

    async def handler(_args, _ctx):
        return json.dumps({"untrusted": True, "content": "docs"})

    registry.register("fetch_page", "fetch", Args, handler)
    provider = MockProvider([
        MockResponse.with_tool("fetch-1", "fetch_page", {"url": "https://docs.example.com"}),
        MockResponse.text("done"),
    ])
    orchestrator = AgentOrchestrator(
        provider=provider,
        registry=registry,
        policy_engine=PolicyEngine("READONLY"),
        audit=audit.log_file,
        ctx=Ctx(),
        on_event=on_event,
    )

    result = asyncio.run(orchestrator.run_turn([{"role": "user", "content": "research docs"}]))

    assert result.state == TurnState.IDLE
    assert any(kind == "research_start" for kind, _ in events)
    assert any(event.get("to_state") == "researching" for event in audit.log_file.tail(20))
