from __future__ import annotations

from termux_coder.providers.mock import MockResponse
from termux_coder.tools import fs

from conftest import build_orchestrator


def test_general_prompt_suppresses_unscoped_read_file(e2e_components):
    components = e2e_components
    components["registry"].register(
        "read_file",
        "Read a workspace file",
        fs.ReadFileArgs,
        fs.read_file,
    )
    orch = build_orchestrator(
        components,
        [
            MockResponse.with_tool("bad-read", "read_file", {"path": "iraq"}),
        ],
    )

    import asyncio

    result = asyncio.run(orch.run_turn([{"role": "user", "content": "iraq"}]))

    assert result.state.value == "idle"
    assert result.tool_results == []
    assert "iraq" not in components["state"].read_files
    assert any(kind == "tool_suppressed" for kind, _ in components["ui"].events)
