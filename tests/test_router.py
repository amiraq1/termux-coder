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
