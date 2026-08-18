import pytest

from termux_coder.cli import build_registry
from termux_coder.providers.router import FAST_EXCLUDE, ModelRouter


def router():
    return ModelRouter(None, None, "8b", "70b", ui=None)


def test_looks_like_edit_arabic():
    assert ModelRouter.looks_like_edit("غيّر قيمة x في demo.py إلى 99")
    assert ModelRouter.looks_like_edit("أصلح فشل الاختبارات")


def test_looks_like_exploration():
    assert not ModelRouter.looks_like_edit("افحص المشروع واشرح البنية")
    assert not ModelRouter.looks_like_edit("hi")


def test_initial_tiers():
    r = router()
    assert r.tier_for_round(0, "hi", []) == ("fast", "exploration")
    assert r.tier_for_round(0, "عدّل السطر الثاني", [])[0] == "smart"
    assert r.tier_for_round(0, "شغّل pytest", [])[0] == "smart"


def test_forced_override():
    r = router()
    r.forced = "fast"
    assert r.tier_for_round(0, "عدّل كل شيء", [])[0] == "fast"


def test_repair_signal_from_last_tool_only():
    r = router()
    msgs = [
        {"role": "tool", "content": "Traceback (most recent call last):"},
        {"role": "tool", "content": "all good now"},
    ]
    # الإشارة القديمة ليست الأخيرة → لا تصعيد
    assert r.tier_for_round(1, "أكمل", msgs) == ("fast", "exploration")
    msgs.append({"role": "tool", "content": "exit=1"})
    assert r.tier_for_round(2, "أكمل", msgs) == ("smart", "repair_signal")


def test_edit_mode_resets_per_turn():
    r = router()
    r.note_edit("apply_patch")
    assert r.edit_mode is True
    r.begin_turn()
    assert r.edit_mode is False
    assert r.tier_for_round(0, "لخّص الملف", [])[0] == "fast"


def test_edit_mode_sticky_within_turn():
    r = router()
    r.note_edit("apply_patch")
    assert r.tier_for_round(2, "أكمل", []) == ("smart", "edit_mode")


def test_fast_cannot_execute_mutation_tools():
    reg = build_registry()
    fast_names = {s["function"]["name"] for s in reg.schemas(exclude=FAST_EXCLUDE)}

    assert "apply_patch" not in fast_names
    assert "write_file" not in fast_names
    assert "delete_file" not in fast_names
    assert "run_command" not in fast_names
    assert "git_commit" not in fast_names
    assert "git_restore" not in fast_names

    assert "read_file" in fast_names
    assert "search_text" in fast_names
    assert "git_status" in fast_names
    assert "repo_map" in fast_names
    assert "lsp_diagnostics" in fast_names



def test_research_summary_into_arabic_file_uses_smart_tier():
    r = router()
    text = "ابحث عن أحدث ميزات Python 3.13 ولخصها لي في ملف اسمه features.md"
    assert r.tier_for_round(0, text, []) == ("smart", "edit_intent")


def test_research_summary_into_english_file_uses_smart_tier():
    r = router()
    text = "Search the latest Python 3.13 docs and summarize them into a file"
    assert r.tier_for_round(0, text, []) == ("smart", "edit_intent")


def test_read_only_research_remains_fast():
    r = router()
    text = "ابحث عن أحدث ميزات Python 3.13 ولخصها لي"
    assert r.tier_for_round(0, text, []) == ("fast", "exploration")


@pytest.mark.anyio
async def test_adapter_keeps_write_tools_for_research_file_output():
    from contextlib import nullcontext
    from termux_coder.core.orchestrator_adapter import RouterProviderAdapter

    class StubUI:
        def thinking(self):
            return nullcontext()

        async def on_event(self, *args, **kwargs):
            return None

    class StubProvider:
        def __init__(self):
            self.tools = []

        async def chat_stream(self, messages, tools, on_token):
            self.tools = tools
            return {"message": {"role": "assistant", "content": "ok"}}

    fast = StubProvider()
    smart = StubProvider()
    adapter = RouterProviderAdapter(
        router=ModelRouter(fast, smart, "fast", "smart", StubUI()),
        ui=StubUI(),
        user_text="ابحث عن أحدث وثائق Python ولخصها لي في ملف features.md",
    )
    schemas = [
        {"function": {"name": "read_file"}},
        {"function": {"name": "write_file"}},
        {"function": {"name": "apply_patch"}},
    ]
    await adapter.chat_stream([], schemas, lambda _: None)
    assert {item["function"]["name"] for item in smart.tools} == {
        "read_file", "write_file", "apply_patch"
    }
