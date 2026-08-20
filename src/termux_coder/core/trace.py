from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..security.scrubber import SecretScrubber

TRACE_SCHEMA_VERSION = 1

# Replay is intentionally read-only in the first implementation.
REPLAY_SAFE_TOOLS = frozenset(
    {
        "read_file",
        "list_dir",
        "search_text",
        "repo_map",
        "git_status",
        "git_diff",
        "git_log",
        "lsp_diagnostics",
    }
)


class TraceStore:
    """Append-only, scrubbed JSONL execution trace storage."""

    def __init__(
        self,
        path: Path,
        *,
        scrubber: SecretScrubber | None = None,
        max_record_chars: int = 16_000,
    ) -> None:
        self.path = path
        self.scrubber = scrubber or SecretScrubber()
        self.max_record_chars = max_record_chars
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _hash_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()

    @classmethod
    def _summary(cls, value: str | None) -> dict[str, Any]:
        text = value or ""
        return {"chars": len(text), "sha256": cls._hash_text(text)[:16]}

    def append(self, trace_id: str, event: str, **data: Any) -> None:
        record: dict[str, Any] = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "trace_id": trace_id,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **data,
        }
        safe_record = self.scrubber.scrub(record)
        raw = json.dumps(safe_record, ensure_ascii=False, separators=(",", ":"))
        if len(raw) > self.max_record_chars:
            safe_record = {
                "schema_version": TRACE_SCHEMA_VERSION,
                "trace_id": trace_id,
                "ts_utc": safe_record["ts_utc"],
                "event": event,
                "truncated": True,
            }
            raw = json.dumps(safe_record, ensure_ascii=False, separators=(",", ":"))
        try:
            with self._lock:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(raw + "\n")
        except OSError:
            # Trace must never bring down a coding turn.
            return

    @staticmethod
    def _bundle_fields(
        task_id: str | None,
        related_paths: list[str] | tuple[str, ...] | None,
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if task_id:
            fields["task_id"] = task_id
        if related_paths:
            fields["related_paths"] = sorted({str(path) for path in related_paths})
        return fields

    def turn_start(
        self,
        trace_id: str,
        user_text: str,
        *,
        model: str | None = None,
        task_id: str | None = None,
        related_paths: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.append(
            trace_id,
            "turn_start",
            user=self._summary(user_text),
            model=model or "",
            **self._bundle_fields(task_id, related_paths),
        )

    def tool_call(
        self,
        trace_id: str,
        *,
        step: int,
        call_id: str,
        tool: str,
        arguments: dict[str, Any],
        round_index: int,
        task_id: str | None = None,
        related_paths: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "step": step,
            "round": round_index,
            "call_id": call_id,
            "tool": tool,
            "arguments_sha256": self._hash_text(
                json.dumps(arguments, sort_keys=True, ensure_ascii=False)
            )[:16],
        }
        # Only replay-safe tool arguments are persisted. Write, shell, and
        # network payloads remain fingerprints, never replay material.
        if tool in REPLAY_SAFE_TOOLS:
            payload["arguments"] = arguments
        self.append(
            trace_id,
            "tool_call",
            **payload,
            **self._bundle_fields(task_id, related_paths),
        )

    def tool_result(
        self,
        trace_id: str,
        *,
        step: int,
        call_id: str,
        tool: str,
        ok: bool,
        duration_ms: int,
        content: str = "",
        error_code: str | None = None,
        task_id: str | None = None,
        related_paths: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.append(
            trace_id,
            "tool_result",
            step=step,
            call_id=call_id,
            tool=tool,
            ok=ok,
            duration_ms=duration_ms,
            result=self._summary(content),
            error_code=error_code or "",
            **self._bundle_fields(task_id, related_paths),
        )

    def turn_end(
        self,
        trace_id: str,
        *,
        state: str,
        rounds: int,
        error: str | None = None,
        task_id: str | None = None,
        related_paths: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.append(
            trace_id,
            "turn_end",
            state=state,
            rounds=rounds,
            error=(error or "")[:500],
            **self._bundle_fields(task_id, related_paths),
        )

    def read(self, trace_id: str) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("trace_id") == trace_id:
                records.append(record)
        return records

    def list_traces(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        latest: dict[str, dict[str, Any]] = {}
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            trace_id = record.get("trace_id")
            if not trace_id:
                continue
            item = latest.setdefault(
                trace_id,
                {"trace_id": trace_id, "started_at": None, "ended_at": None, "state": None, "rounds": 0},
            )
            if record.get("event") == "turn_start":
                item["started_at"] = record.get("ts_utc")
                item["model"] = record.get("model", "")
            elif record.get("event") == "turn_end":
                item["ended_at"] = record.get("ts_utc")
                item["state"] = record.get("state")
                item["rounds"] = record.get("rounds", 0)
        return list(latest.values())[-limit:]
