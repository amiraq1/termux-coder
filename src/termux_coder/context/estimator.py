from __future__ import annotations


class TokenEstimator:
    """
    تقدير الرموز: fallback سريع للـ Termux.
    يمكن استبداله لاحقًا بـ tiktoken أو model-specific tokenizer.
    """

    def estimate(self, text: str) -> int:
        """
        تقدير تقريبي: ~4 أحرف لكل token (متوسط الإنجليزية/البرمجة).
        للعربية قد يكون أقل (2-3 أحرف/token)، لكن هذا safe estimate.
        """
        if not text:
            return 0
        return max(1, len(text) // 4)

    def estimate_message(self, message: dict) -> int:
        """تقدير رسالة كاملة مع metadata."""
        content = message.get("content") or ""
        extra = 0

        # overhead للـ role و JSON structure
        extra += 10

        # tool_calls
        tool_calls = message.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                args = func.get("arguments", "")
                extra += 20 + self.estimate(name) + self.estimate(args)

        # tool_call_id
        if message.get("tool_call_id"):
            extra += 15

        return self.estimate(content) + extra
