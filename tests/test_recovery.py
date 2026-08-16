import json

from termux_coder.core.recovery import recover_tool_calls
from termux_coder.tools.patch import recover_simple_patch


class FakeRegistry:
    def handler(self, name):
        return (lambda a, c: "") if name == "apply_patch" else None


def test_recover_tool_call_from_text():
    content = (
        'I apologize, here is the call: '
        '{"name": "apply_patch", "parameters": {"path": "demo.py", '
        '"patch": "x = 1\\nx = 99"}}'
    )
    calls = recover_tool_calls(content, FakeRegistry())
    assert calls and calls[0]["function"]["name"] == "apply_patch"
    args = json.loads(calls[0]["function"]["arguments"])
    assert args["path"] == "demo.py"


def test_no_recovery_for_plain_text():
    assert recover_tool_calls("مرحبا، لا يوجد JSON هنا", FakeRegistry()) is None


def test_no_recovery_for_unknown_tool():
    content = '{"name": "hack_the_planet", "parameters": {}}'
    assert recover_tool_calls(content, FakeRegistry()) is None


def test_recover_simple_patch_literal_newline():
    source = "x = 1\n"
    assert recover_simple_patch("x = 1\\nx = 99", source) == ("x = 1", "x = 99")


def test_recover_simple_patch_rejects_ambiguous():
    source = "x = 1\nx = 1\n"
    assert recover_simple_patch("x = 1\\nx = 99", source) is None


def test_recover_simple_patch_rejects_multiline():
    assert recover_simple_patch("a\\nb\\nc", "a\n") is None
