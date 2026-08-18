from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from termux_coder.core.context import SessionState
from termux_coder.security.audit import AuditLog
from termux_coder.security.jail import WorkspaceJail
from termux_coder.tools.edit import apply_symbol_patch
from termux_coder.tools.preview import PatchPreviewService
from termux_coder.tools.symbol import SymbolPatchArgs


class UI:
    def __init__(self, approved=True):
        self.approved = approved
        self.approvals = []
        self.events = []

    async def request_approval(self, kind, payload):
        self.approvals.append((kind, payload))
        return self.approved

    async def on_event(self, kind, **payload):
        self.events.append((kind, payload))


def make_context(tmp_path: Path, source: str):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "app.py"
    path.write_text(source, encoding="utf-8")
    state = SessionState(
        read_files={"app.py"},
        read_hashes={"app.py": hashlib.sha256(source.encode()).hexdigest()},
    )
    settings = SimpleNamespace(backup_dir=tmp_path / "backups")
    return (
        SimpleNamespace(
            jail=WorkspaceJail(workspace),
            state=state,
            settings=settings,
            ui=UI(),
            audit=AuditLog(tmp_path / "audit.jsonl"),
            lsp=None,
        ),
        path,
    )


def test_apply_symbol_patch_changes_only_target_symbol(tmp_path):
    source = (
        "def target(value):\n"
        "    return value + 1\n"
        "\n"
        "def other(value):\n"
        "    return value + 9\n"
    )
    ctx, path = make_context(tmp_path, source)

    result = asyncio.run(
        apply_symbol_patch(
            SymbolPatchArgs(
                path="app.py",
                name="target",
                kind="function",
                expected_signature="def target(value):",
                replacement="def target(value):\n    return value * 2",
            ),
            ctx,
        )
    )

    updated = path.read_text(encoding="utf-8")
    assert result == "patch applied to app.py"
    assert "return value * 2" in updated
    assert "return value + 9" in updated
    assert ctx.ui.approvals[0][0] == "patch"
    assert len(ctx.state.applied_patches) == 1


def test_symbol_patch_rejects_path_outside_workspace(tmp_path):
    ctx, _path = make_context(tmp_path, "def target():\n    return 1\n")

    result = asyncio.run(
        apply_symbol_patch(
            SymbolPatchArgs(
                path="../outside.py",
                name="target",
                kind="function",
                replacement="def target():\n    return 2",
            ),
            ctx,
        )
    )

    assert result.startswith("symbol patch error:")


def test_symbol_patch_rejects_toctou_change(tmp_path):
    ctx, path = make_context(tmp_path, "def target():\n    return 1\n")
    path.write_text("def target():\n    return 99\n", encoding="utf-8")

    result = asyncio.run(
        apply_symbol_patch(
            SymbolPatchArgs(
                path="app.py",
                name="target",
                kind="function",
                replacement="def target():\n    return 2",
            ),
            ctx,
        )
    )

    assert "modified after you read it" in result


def test_symbol_preview_has_exact_result_hash(tmp_path):
    source = "def target():\n    return 1\n"
    ctx, _path = make_context(tmp_path, source)
    preview = PatchPreviewService(ctx.jail, ctx.state).generate_symbol(
        "app.py",
        "target",
        "function",
        "def target():\n    return 2",
    )

    assert preview.path == "app.py"
    assert preview.additions == 1
    assert preview.removals == 1
    assert len(preview.source_hash) == 64
    assert len(preview.result_hash) == 64
    assert "return 2" in preview.diff


def test_orchestrator_symbol_patch_uses_preview_and_approval(tmp_path):
    from termux_coder.core.orchestrator import AgentOrchestrator, TurnState
    from termux_coder.core.registry import ToolRegistry
    from termux_coder.models.contracts import ToolResult
    from termux_coder.providers.mock import MockProvider, MockResponse
    from termux_coder.security.policy import PolicyEngine

    source = "def target():\n    return 1\n"
    ctx, path = make_context(tmp_path, source)
    registry = ToolRegistry()
    registry.register("apply_symbol_patch", "symbol patch", SymbolPatchArgs, apply_symbol_patch)
    provider = MockProvider([
        MockResponse.with_tool(
            "symbol-1",
            "apply_symbol_patch",
            {
                "path": "app.py",
                "name": "target",
                "kind": "function",
                "replacement": "def target():\n    return 2",
            },
        ),
        MockResponse.text("done"),
    ])
    events = []

    async def on_event(kind, **payload):
        events.append((kind, payload))

    async def approve(kind, payload):
        assert kind == "patch"
        assert "return 2" in payload["diff"]
        return True

    orchestrator = AgentOrchestrator(
        provider=provider,
        registry=registry,
        policy_engine=PolicyEngine("ASK"),
        audit=ctx.audit,
        ctx=ctx,
        max_rounds=3,
        max_duration_s=10,
        on_event=on_event,
        approval_handler=approve,
        preview_service=PatchPreviewService(ctx.jail, ctx.state),
    )

    result = asyncio.run(
        orchestrator.run_turn([{"role": "user", "content": "change target"}])
    )

    assert result.state == TurnState.IDLE
    assert path.read_text(encoding="utf-8") == "def target():\n    return 2\n"
    assert any(kind == "approval_requested" for kind, _ in events)
