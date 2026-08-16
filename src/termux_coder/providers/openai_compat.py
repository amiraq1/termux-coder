from __future__ import annotations

from openai import AsyncOpenAI


class OpenAICompatProvider:
    def __init__(self, api_key: str, base_url: str, model: str):
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def chat_stream(self, messages: list[dict], tools: list[dict], on_token) -> dict:
        kwargs: dict = {"model": self.model, "messages": messages, "stream": True}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        content = ""
        tool_calls: dict[int, dict] = {}

        stream = await self.client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                content += delta.content
                await on_token(delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    slot = tool_calls.setdefault(
                        tc.index or 0, {"id": "", "name": "", "arguments": ""}
                    )
                    if tc.id:
                        slot["id"] += tc.id
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"] += tc.function.arguments

        if tool_calls:
            return {
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": s["id"],
                        "type": "function",
                        "function": {"name": s["name"], "arguments": s["arguments"]},
                    }
                    for s in tool_calls.values()
                ],
            }
        return {"role": "assistant", "content": content}
