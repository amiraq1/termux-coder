from __future__ import annotations

import json
import re


def recover_tool_calls(content: str, registry) -> list[dict] | None:
    """
    بعض النماذج (NVIDIA NIM، نماذج محلية) لا تولّد tool_calls أصلية،
    بل تطبع الاستدعاء كـ JSON نصي داخل الرد.
    نستخرجه هنا ونحوّله إلى استدعاء أدوات سليم.
    """
    if not content or "{" not in content:
        return None
    if '"name"' not in content and '"tool"' not in content:
        return None

    decoder = json.JSONDecoder()
    calls: list[dict] = []

    for match in re.finditer(r"\{", content):
        try:
            obj, _ = decoder.raw_decode(content[match.start():])
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue

        name = obj.get("name") or obj.get("tool")
        params = obj.get("parameters") or obj.get("arguments") or obj.get("args")

        if not name and isinstance(obj.get("function"), dict):
            name = obj["function"].get("name")
            params = params or obj["function"].get("arguments")

        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                params = None

        if name and isinstance(params, dict) and registry.handler(name):
            calls.append(
                {
                    "id": f"recovered-{len(calls) + 1}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(params)},
                }
            )

    return calls or None
