from __future__ import annotations

from openai import AsyncOpenAI


def _clean_ascii(value: str) -> str:
    """إزالة أي حروف غير ASCII (اقتباسات عربية، مسافات غريبة، placeholder)."""
    return "".join(ch for ch in (value or "") if ch.isascii()).strip()


class OpenAICompatProvider:
    def __init__(self, api_key: str, base_url: str, model: str):
        api_key = _clean_ascii(api_key)
        base_url = _clean_ascii(base_url)

        if not api_key or api_key == "EMPTY":
            raise RuntimeError(
                "لا يوجد مفتاح API صالح. حرّر ~/termux-coder/env_nvidia.sh "
                "باقتباسات إنجليزية مستقيمة ثم: source ~/.bashrc"
            )
        if not base_url:
            raise RuntimeError("OPENAI_BASE_URL فارغ.")

        self.model = model
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def chat_stream(self, messages: list[dict], tools: list[dict], on_token) -> dict:
        """لا نرسل tools - نعتمد على Recovery Layer"""
        # لا نرسل tools parameter
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
        )
        
        content = ""
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                content += text
                await on_token(text)
        
        return {"role": "assistant", "content": content}
