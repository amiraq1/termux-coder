from types import SimpleNamespace

from termux_coder.core.orchestrator import AgentOrchestrator


def test_edit_success_requires_successful_mutation_tool() -> None:
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._tool_results = [
        SimpleNamespace(ok=False, tool="apply_patch"),
        SimpleNamespace(ok=True, tool="read_file"),
    ]
    assert orchestrator._has_successful_edit() is False

    orchestrator._tool_results.append(SimpleNamespace(ok=True, tool="apply_patch"))
    assert orchestrator._has_successful_edit() is True


def test_preview_or_denial_is_not_a_successful_edit() -> None:
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._tool_results = [
        SimpleNamespace(ok=False, tool="apply_patch"),
        SimpleNamespace(ok=False, tool="apply_patch", preview={}),
    ]
    assert orchestrator._has_successful_edit() is False
