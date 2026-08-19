from types import SimpleNamespace

from termux_coder.ui.app import PromptInput


class _Event:
    def __init__(self, key):
        self.key = key
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_prompt_input_routes_context_actions_shortcuts():
    calls = []
    owner = SimpleNamespace(
        action_toggle_context_actions=lambda: calls.append("toggle"),
        action_copy_last_answer=lambda: calls.append("copy"),
    )
    prompt = PromptInput(owner)

    toggle_event = _Event("ctrl+m")
    prompt.on_key(toggle_event)
    copy_event = _Event("ctrl+shift+c")
    prompt.on_key(copy_event)

    assert calls == ["toggle", "copy"]
    assert toggle_event.stopped is True
    assert copy_event.stopped is True
