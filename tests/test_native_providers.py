from __future__ import annotations

from termux_coder.providers.native import (
    _anthropic_messages,
    _anthropic_tools,
    _gemini_contents,
    _gemini_tools,
)


def _history():
    return [
        {"role": "system", "content": "Follow the safety policy."},
        {"role": "user", "content": "Read main.py"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"main.py"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "print('ok')"},
    ]


def _tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }
    ]


def test_anthropic_message_and_tool_conversion():
    system, messages = _anthropic_messages(_history())
    tools = _anthropic_tools(_tools())

    assert system == "Follow the safety policy."
    assert messages[0] == {"role": "user", "content": "Read main.py"}
    assert messages[1]["content"][0]["type"] == "tool_use"
    assert messages[1]["content"][0]["input"] == {"path": "main.py"}
    assert messages[2]["content"][0]["type"] == "tool_result"
    assert tools[0]["input_schema"]["required"] == ["path"]


def test_gemini_message_and_tool_conversion():
    contents, system = _gemini_contents(_history())
    tools = _gemini_tools(_tools())

    assert system == "Follow the safety policy."
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model"
    assert contents[1]["parts"][0]["functionCall"]["name"] == "read_file"
    assert contents[2]["parts"][0]["functionResponse"]["name"] == "read_file"
    assert tools[0]["functionDeclarations"][0]["name"] == "read_file"


def test_gemini_tool_result_uses_call_name_from_assistant_history():
    contents, _ = _gemini_contents(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "abc",
                        "function": {
                            "name": "search_text",
                            "arguments": "{}",
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "abc", "content": "result"},
        ]
    )

    assert contents[1]["parts"][0]["functionResponse"]["name"] == "search_text"
