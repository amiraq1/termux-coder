from __future__ import annotations

import json
import re
import os

def normalize_path(path: str, workspace: str) -> str:
    """تحويل المسار المطلق إلى نسبي"""
    workspace = workspace.rstrip("/")
    if path.startswith(workspace + "/"):
        return path[len(workspace) + 1:]
    return path


def sanitize_tool_calls(raw_calls: list[dict]) -> tuple[list[dict], list[dict]]:
    """Canonicalize native tool-call arguments before they enter conversation history."""
    sanitized: list[dict] = []
    errors: list[dict] = []
    for raw in raw_calls:
        call = dict(raw) if isinstance(raw, dict) else {}
        function = dict(call.get("function") or {})
        name = str(function.get("name") or "")
        call_id = call.get("id") or ""
        raw_args = function.get("arguments") or "{}"
        try:
            parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            if not isinstance(parsed, dict):
                raise ValueError("tool arguments must be a JSON object")
            function["arguments"] = json.dumps(parsed, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            snippet = raw_args[:200] if isinstance(raw_args, str) else str(raw_args)[:200]
            function["arguments"] = "{}"
            errors.append({"call_id": call_id, "tool": name, "raw": snippet, "error": str(exc)})
        call["function"] = function
        sanitized.append(call)
    return sanitized, errors


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
            # تطبيع المسارات
            if "path" in params and isinstance(params["path"], str):
                workspace = os.getcwd()
                params["path"] = normalize_path(params["path"], workspace)
            
            # فك هروب \n في patch
            if name == "apply_patch" and "patch" in params:
                patch = params["patch"]
                if "\\n" in patch:
                    params["patch"] = patch.replace("\\n", "\n")
                
            calls.append(
                {
                    "id": f"recovered-{len(calls) + 1}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(params)},
                }
            )

    return calls or None
