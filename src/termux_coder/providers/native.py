from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx


def _json_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts)
    return ""


def _tool_function(tool: dict[str, Any]) -> dict[str, Any]:
    return tool.get("function", tool)


def _anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted = []
    for tool in tools:
        fn = _tool_function(tool)
        converted.append(
            {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get(
                    "parameters", {"type": "object", "properties": {}}
                ),
            }
        )
    return converted


def _gemini_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    declarations = []
    for tool in tools:
        fn = _tool_function(tool)
        declarations.append(
            {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get(
                    "parameters", {"type": "object", "properties": {}}
                ),
            }
        )
    return [{"functionDeclarations": declarations}] if declarations else []


def _append_content(messages: list[dict[str, Any]], role: str, content: Any) -> None:
    if messages and messages[-1]["role"] == role and isinstance(messages[-1]["content"], list):
        if isinstance(content, list):
            messages[-1]["content"].extend(content)
        else:
            messages[-1]["content"].append(content)
        return
    messages.append({"role": role, "content": content})


def _append_gemini_content(contents: list[dict[str, Any]], role: str, parts: list[dict[str, Any]]) -> None:
    if contents and contents[-1]["role"] == role:
        contents[-1].setdefault("parts", []).extend(parts)
        return
    contents.append({"role": role, "parts": parts})


def _anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            text = _text_content(message.get("content"))
            if text:
                system_parts.append(text)
            continue
        if role == "user":
            _append_content(converted, "user", message.get("content", ""))
            continue
        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            text = _text_content(message.get("content"))
            if text:
                blocks.append({"type": "text", "text": text})
            for call in message.get("tool_calls", []) or []:
                fn = call.get("function", {})
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.get("id") or "tool-call",
                        "name": fn.get("name", ""),
                        "input": _json_arguments(fn.get("arguments", "{}")),
                    }
                )
            if blocks:
                _append_content(converted, "assistant", blocks)
            continue
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message.get("tool_call_id", "tool-call"),
                "content": str(message.get("content", "")),
            }
            _append_content(converted, "user", [block])
    return "\n\n".join(system_parts), converted


def _gemini_contents(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    contents: list[dict[str, Any]] = []
    system_parts: list[str] = []
    call_names: dict[str, str] = {}
    for message in messages:
        role = message.get("role")
        if role == "system":
            text = _text_content(message.get("content"))
            if text:
                system_parts.append(text)
            continue
        if role == "user":
            _append_gemini_content(contents, "user", [{"text": _text_content(message.get("content"))}])
            continue
        if role == "assistant":
            parts: list[dict[str, Any]] = []
            text = _text_content(message.get("content"))
            if text:
                parts.append({"text": text})
            for call in message.get("tool_calls", []) or []:
                call_id = call.get("id") or f"gemini-call-{len(call_names)}"
                fn = call.get("function", {})
                name = fn.get("name", "")
                call_names[call_id] = name
                parts.append(
                    {
                        "functionCall": {
                            "name": name,
                            "args": _json_arguments(fn.get("arguments", "{}")),
                        }
                    }
                )
            if parts:
                _append_gemini_content(contents, "model", parts)
            continue
        if role == "tool":
            call_id = message.get("tool_call_id", "")
            name = message.get("tool_name") or call_names.get(call_id, "tool")
            result = message.get("content", "")
            _append_gemini_content(
                contents,
                "user",
                [
                    {
                        "functionResponse": {
                            "name": name,
                            "response": {"result": result},
                        }
                    }
                ],
            )
    return contents, "\n\n".join(system_parts)


async def _sse_events(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
        elif not line.strip() and data_lines:
            raw = "".join(data_lines)
            data_lines.clear()
            if raw and raw != "[DONE]":
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    yield item
    if data_lines:
        raw = "".join(data_lines)
        if raw and raw != "[DONE]":
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                return
            if isinstance(item, dict):
                yield item


class AnthropicProvider:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = int(os.environ.get("TERMUX_CODER_MAX_OUTPUT_TOKENS", "2048"))
        if not self.api_key or self.api_key == "EMPTY":
            raise RuntimeError("No valid Anthropic API key found; configure ANTHROPIC_API_KEY.")
        if not self.base_url:
            raise RuntimeError("ANTHROPIC_BASE_URL is empty.")

    async def chat_stream(self, messages: list[dict], tools: list[dict], on_token) -> dict:
        system, converted = _anthropic_messages(messages)
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": converted,
            "stream": True,
        }
        if system:
            request["system"] = system
        if tools:
            request["tools"] = _anthropic_tools(tools)
            if os.environ.get("TERMUX_CODER_SINGLE_TOOL_CALLS", "1") == "1":
                request["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", f"{self.base_url}/messages", headers=headers, json=request
            ) as response:
                response.raise_for_status()
                content = ""
                calls: dict[int, dict[str, Any]] = {}
                async for event in _sse_events(response):
                    event_type = event.get("type")
                    if event_type == "content_block_start":
                        index = int(event.get("index", len(calls)))
                        block = event.get("content_block", {})
                        if block.get("type") == "tool_use":
                            calls[index] = {
                                "id": block.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": block.get("name", ""),
                                    "arguments": "",
                                },
                            }
                    elif event_type == "content_block_delta":
                        index = int(event.get("index", 0))
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            content += text
                            if text:
                                await on_token(text)
                        elif delta.get("type") == "input_json_delta" and index in calls:
                            calls[index]["function"]["arguments"] += delta.get(
                                "partial_json", ""
                            )
        result: dict[str, Any] = {"role": "assistant", "content": content}
        if calls:
            result["tool_calls"] = [calls[i] for i in sorted(calls)]
        return result


class GeminiProvider:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model.removeprefix("models/")
        if not self.api_key or self.api_key == "EMPTY":
            raise RuntimeError("No valid Gemini API key found; configure GEMINI_API_KEY.")
        if not self.base_url:
            raise RuntimeError("GEMINI_BASE_URL is empty.")

    async def chat_stream(self, messages: list[dict], tools: list[dict], on_token) -> dict:
        contents, system = _gemini_contents(messages)
        request: dict[str, Any] = {"contents": contents}
        if system:
            request["systemInstruction"] = {"parts": [{"text": system}]}
        gemini_tools = _gemini_tools(tools)
        if gemini_tools:
            request["tools"] = gemini_tools

        model_path = quote(self.model, safe="._- /").replace(" ", "%20")
        url = f"{self.base_url}/models/{model_path}:streamGenerateContent?alt=sse"
        headers = {"x-goog-api-key": self.api_key, "content-type": "application/json"}
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, headers=headers, json=request) as response:
                response.raise_for_status()
                content = ""
                calls: list[dict[str, Any]] = []
                async for event in _sse_events(response):
                    for candidate in event.get("candidates", []) or []:
                        candidate_content = candidate.get("content", {})
                        for part in candidate_content.get("parts", []) or []:
                            text = part.get("text", "")
                            if text:
                                content += text
                                await on_token(text)
                            function_call = part.get("functionCall")
                            if isinstance(function_call, dict):
                                name = function_call.get("name", "")
                                call_id = f"gemini-call-{len(calls)}"
                                calls.append(
                                    {
                                        "id": call_id,
                                        "type": "function",
                                        "function": {
                                            "name": name,
                                            "arguments": json.dumps(
                                                function_call.get("args", {}),
                                                ensure_ascii=False,
                                                separators=(",", ":"),
                                            ),
                                        },
                                    }
                                )
        result: dict[str, Any] = {"role": "assistant", "content": content}
        if calls:
            result["tool_calls"] = calls
        return result
