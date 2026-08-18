from __future__ import annotations

import asyncio
import hashlib

import pytest

from termux_coder.providers.mock import MockResponse
from termux_coder.security.jail import JailViolation
from termux_coder.tools import fs

from conftest import E2EUI, build_orchestrator


def patch_text(old: str, new: str) -> str:
    return f"<<<<<<< SEARCH\n{old}\n=======\n{new}\n>>>>>>> REPLACE"


def run(coro):
    return asyncio.run(coro)


def test_read_search_and_workspace_boundary(e2e_components):
    async def scenario():
        components = e2e_components
        ctx = components["ctx"]
        components["state"].read_files.clear()
        components["state"].read_hashes.clear()

        content = await fs.read_file(fs.ReadFileArgs(path="main.py"), ctx)
        assert "def greet" in content
        assert "main.py" in components["state"].read_files
        assert components["state"].read_hashes["main.py"] == hashlib.sha256(
            content.encode("utf-8")
        ).hexdigest()

        generated_dir = components["workspace"] / ".termux_coder" / "backups"
        generated_dir.mkdir(parents=True)
        (generated_dir / "main.py.bak").write_text("greet", encoding="utf-8")
        (components["workspace"] / "run.log").write_text("greet", encoding="utf-8")
        (components["workspace"] / ".termux_coder" / "audit.jsonl").write_text(
            "greet", encoding="utf-8"
        )

        matches = await fs.search_text(fs.SearchTextArgs(query="greet", path="."), ctx)
        assert "main.py" in matches
        assert "run.log" not in matches
        assert ".termux_coder" not in matches
        assert ".bak" not in matches

        with pytest.raises(JailViolation):
            await fs.read_file(fs.ReadFileArgs(path="/etc/passwd"), ctx)

    run(scenario())


def test_patch_is_refused_before_read_and_leaves_file_unchanged(e2e_components):
    async def scenario():
        components = e2e_components
        path = components["workspace"] / "main.py"
        original = path.read_text(encoding="utf-8")
        components["state"].read_files.clear()
        components["state"].read_hashes.clear()

        patch = patch_text('return "Hello, " + name', 'return "Changed"')
        orch = build_orchestrator(
            components,
            [MockResponse.with_tool("pre-read", "apply_patch", {"path": "main.py", "patch": patch})],
        )
        result = await orch.run_turn([{"role": "user", "content": "edit without reading"}])

        assert result.state.value == "idle"
        assert path.read_text(encoding="utf-8") == original
        assert result.tool_results
        assert result.tool_results[0].ok is False
        assert result.tool_results[0].error is not None
        assert "must read_file(main.py)" in result.tool_results[0].error.message

    run(scenario())


def test_approved_patch_exposes_preview_and_applies_change(e2e_components):
    async def scenario():
        components = e2e_components
        captured: dict[str, object] = {}
        path = components["workspace"] / "main.py"
        patch = patch_text('return "Hello, " + name', 'return "Approved"')

        def capture_approval(kind, payload):
            captured["kind"] = kind
            captured["payload"] = payload

        ui = E2EUI(approve=True, before_approval=capture_approval)
        orch = build_orchestrator(
            components,
            [
                MockResponse.with_tool("approved", "apply_patch", {"path": "main.py", "patch": patch}),
                MockResponse.text("Done."),
            ],
            ui=ui,
        )
        result = await orch.run_turn([{"role": "user", "content": "edit safely"}])

        assert result.state.value == "idle"
        assert 'return "Approved"' in path.read_text(encoding="utf-8")
        assert captured["kind"] == "patch"
        payload = captured["payload"]
        assert payload["risk"] == "high"
        assert 'return "Approved"' in payload["diff"]
        audit_text = (components["workspace"] / ".termux_coder" / "audit.jsonl").read_text(
            encoding="utf-8"
        )
        assert '"event": "patch_preview"' in audit_text

    run(scenario())


def test_rejected_patch_is_visible_and_does_not_modify_file(e2e_components):
    async def scenario():
        components = e2e_components
        path = components["workspace"] / "main.py"
        original = path.read_text(encoding="utf-8")
        components["ui"] = E2EUI(approve=False)
        patch = patch_text('return "Hello, " + name', 'return "Rejected"')
        orch = build_orchestrator(
            components,
            [MockResponse.with_tool("reject", "apply_patch", {"path": "main.py", "patch": patch})],
            ui=components["ui"],
        )
        result = await orch.run_turn([{"role": "user", "content": "edit"}])

        assert result.state.value == "cancelled"
        assert path.read_text(encoding="utf-8") == original
        assert any(kind == "approval_requested" for kind, _ in components["ui"].events)
        assert components["state"].applied_patches == []

    run(scenario())
