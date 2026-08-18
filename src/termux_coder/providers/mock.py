"""
mock.py — MockProvider للاختبارات.

يتيح تحديد سيناريو اختبار مسبقًا:
- استجابات نصية بحتة
- استدعاءات أدوات
- رسائل مساعد مع tool_calls صحيحة البنية
"""
from __future__ import annotations

from typing import Any, Callable


class MockResponse:
    """تعريف استجابة واحدة في سيناريو الاختبار."""
    __slots__ = ("content", "tool_calls")

    def __init__(
        self,
        content: str = "",
        tool_calls: list[dict] | None = None,
    ):
        self.content    = content
        self.tool_calls = tool_calls or []

    @classmethod
    def text(cls, content: str) -> "MockResponse":
        return cls(content=content)

    @classmethod
    def with_tool(
        cls,
        call_id: str,
        name: str,
        arguments: dict,
    ) -> "MockResponse":
        """استجابة تحتوي استدعاء أداة واحد — البنية صحيحة للـ API."""
        return cls(
            content="",
            tool_calls=[{
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": __import__("json").dumps(arguments),
                },
            }],
        )

    @classmethod
    def with_tools(cls, calls: list[tuple[str, str, dict]]) -> "MockResponse":
        """
        استجابة تحتوي عدة استدعاءات أدوات.
        calls: [(call_id, name, arguments), ...]
        """
        import json
        return cls(
            content="",
            tool_calls=[
                {
                    "id": cid,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
                for cid, name, args in calls
            ],
        )


class MockProvider:
    """
    مزود وهمي للاختبارات.

    يُغذَّى بقائمة MockResponse تُستهلك بالترتيب.
    بعد نفاد القائمة يُعيد استجابة نصية فارغة.
    """

    def __init__(self, responses: list[MockResponse]):
        self._responses = list(responses)
        self._index     = 0
        self.calls: list[dict] = []  # سجل كل ما طُلب من المزود

    def reset(self, responses: list[MockResponse] | None = None) -> None:
        """إعادة تعيين المزود لسيناريو جديد."""
        self._index = 0
        if responses is not None:
            self._responses = list(responses)
        self.calls.clear()

    @property
    def exhausted(self) -> bool:
        return self._index >= len(self._responses)

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        on_token: Callable,
    ) -> dict:
        """يُحاكي chat_stream: يُرجع الاستجابة التالية كـ dict."""
        self.calls.append({
            "messages_count": len(messages),
            "tools_count": len(tools),
        })

        if self._index >= len(self._responses):
            # قائمة مستنفدة — أعد نصًا فارغًا
            return {"role": "assistant", "content": ""}

        resp = self._responses[self._index]
        self._index += 1

        if resp.content:
            if callable(on_token):
                import inspect
                r = on_token(resp.content)
                if inspect.isawaitable(r):
                    await r

        result: dict[str, Any] = {"role": "assistant", "content": resp.content}
        if resp.tool_calls:
            result["tool_calls"] = resp.tool_calls

        return result
