from types import SimpleNamespace

from termux_coder.ui.app import PromptInput


class _Event:
    def __init__(self, key):
        self.key = key
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_prompt_input_handles_touch_and_escape_without_losing_focus():
    owner = SimpleNamespace()
    prompt = PromptInput(owner)

    focused = []
    prompt.focus = lambda: focused.append(True)
    prompt.on_click(object())
    escape = _Event("escape")
    prompt.on_key(escape)

    assert focused == [True, True]
    assert escape.stopped is True
