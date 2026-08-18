from __future__ import annotations

import os
from collections import defaultdict

from openai import AsyncOpenAI


def _clean_ascii(value: str) -> str:
    """إزالة أي حروف غير ASCII من إعدادات الاتصال."""
    return "".join(ch for ch in (value or "") if ch.isascii()).strip()


class OpenAICompatProvider:
    def __init__(self, api_key: str, base_url: str, model: str):
        api_key = _clean_ascii(api_key)
        base_url = _clean_ascii(base_url)

        if not api_key or api_key == "EMPTY":
            raise RuntimeError(
                "No valid API key found. Configure the environment file "
                "with straight quotes, then reload it before starting the agent."
            )
        if not base_url:
            raise RuntimeError("OPENAI_BASE_URL is empty.")

        self.model = model
        self.single_tool_calls = os.environ.get(
            "TERMUX_CODER_SINGLE_TOOL_CALLS", "1"
        ) == "1"
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def chat_stream(self, messages: list[dict], tools: list[dict], on_token) -> dict:
        """إرسال الأدوات للمزود وجمع النص واستدعاءات الأدوات أثناء البث.

        بعض المزودين المتوافقين لا يدعمون native tool calling؛ في هذه الحالة
        يمكن تعطيل الإرسال عبر ``TERMUX_CODER_NATIVE_TOOLS=0``، وتتكفل طبقة
        Recovery باستخراج الاستدعاء النصي في Orchestrator/Agent.
        """
        native_tools = os.environ.get("TERMUX_CODER_NATIVE_TOOLS", "1") == "1"
        request = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if native_tools and tools:
            request["tools"] = tools
            request["tool_choice"] = "auto"
            if self.single_tool_calls:
                # llama.cpp-compatible servers and some prompt templates reject
                # parallel tool calls even when the API advertises OpenAI shape.
                request["parallel_tool_calls"] = False

        response = await self.client.chat.completions.create(**request)
        content = ""
        calls: dict[int, dict] = defaultdict(
            lambda: {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
        )

        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content += delta.content
                await on_token(delta.content)

            for tool_delta in (getattr(delta, "tool_calls", None) or []):
                index = getattr(tool_delta, "index", 0) or 0
                current = calls[index]
                if getattr(tool_delta, "id", None):
                    current["id"] = tool_delta.id
                if getattr(tool_delta, "type", None):
                    current["type"] = tool_delta.type
                function = getattr(tool_delta, "function", None)
                if function is not None:
                    if getattr(function, "name", None):
                        current["function"]["name"] += function.name
                    if getattr(function, "arguments", None):
                        current["function"]["arguments"] += function.arguments

        result = {"role": "assistant", "content": content}
        if calls:
            result["tool_calls"] = [calls[i] for i in sorted(calls)]
        return result
