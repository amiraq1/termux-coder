from types import SimpleNamespace

from termux_coder.cli import _format_final_answer
from termux_coder.core.detail import wants_detailed_report


def test_repository_analysis_requests_enable_detail_mode():
    assert wants_detailed_report("Inspect the repository and explain its architecture")
    assert wants_detailed_report("فحص المستودع بالتفصيل")
    assert wants_detailed_report("review the project structure and dependencies")


def test_simple_requests_remain_compact():
    assert not wants_detailed_report("what is 1+1")
    assert not wants_detailed_report("list the files")
    assert not wants_detailed_report("hello")


def test_detail_detection_is_turn_local():
    assert not wants_detailed_report("")
    assert wants_detailed_report("analyze the files")


def test_detailed_final_answer_appends_model_context_after_tool_data():
    tool_result = SimpleNamespace(tool="list_dir", ok=True, data="main.py", error=None)
    turn_result = SimpleNamespace(
        final_text="The repository contains a small executable entry point and should be reviewed with its test scripts.",
        tool_results=[tool_result],
    )

    compact = _format_final_answer(None, turn_result, show_thinking=False, detailed=False)
    detailed = _format_final_answer(None, turn_result, show_thinking=False, detailed=True)

    assert compact == "main.py"
    assert "main.py" in detailed
    assert "small executable entry point" in detailed
