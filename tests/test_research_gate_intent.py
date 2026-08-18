from termux_coder.core.orchestrator import requires_current_docs


def test_current_code_value_is_not_research_intent() -> None:
    request = 'Modify main.py so greet returns "Changed" instead of its current return value.'
    assert requires_current_docs(request) is False


def test_explicit_current_documentation_is_research_intent() -> None:
    assert requires_current_docs("Search the official Python documentation for pathlib.Path.resolve") is True
    assert requires_current_docs("Find the latest docs for asyncio.Task") is True


def test_unrelated_latest_word_does_not_trigger_research() -> None:
    assert requires_current_docs("Update the latest commit message") is False
