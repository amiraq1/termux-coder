from __future__ import annotations

import copy
import hashlib
import time
from dataclasses import dataclass
from typing import Any

from ..models.contracts import DecisionKind
from .trace import REPLAY_SAFE_TOOLS, TraceStore


@dataclass(frozen=True)
class ReplayItem:
    step: int
    tool: str
    call_id: str
    status: str
    duration_ms: int = 0
    output: str = ""
    reason: str = ""
    output_sha256: str = ""


class ReplayRunner:
    """Replay only deterministic, read-only trace steps."""

    def __init__(self, trace_store: TraceStore, registry, ctx) -> None:
        self.trace_store = trace_store
        self.registry = registry
        self.ctx = ctx

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]

    async def run(self, trace_id: str, *, from_step: int = 1) -> list[ReplayItem]:
        if from_step < 1:
            raise ValueError("from_step must be >= 1")
        records = self.trace_store.read(trace_id)
        calls = [
            record
            for record in records
            if record.get("event") == "tool_call"
            and int(record.get("step", 0)) >= from_step
        ]
        if not calls:
            raise ValueError(f"trace not found or has no replayable calls: {trace_id}")

        # Never let replay mutate the live Agent state (e.g. read_file hashes).
        replay_ctx = copy.copy(self.ctx)
        if hasattr(self.ctx, "state"):
            replay_ctx.state = copy.deepcopy(self.ctx.state)
            # Replay starts from a clean read snapshot; never mutate or reuse
            # the live session's read-before-write bookkeeping.
            replay_ctx.state.read_files.clear()
            replay_ctx.state.read_hashes.clear()

        results: list[ReplayItem] = []
        for record in calls:
            step = int(record.get("step", 0))
            tool = str(record.get("tool", ""))
            call_id = str(record.get("call_id", ""))
            arguments = record.get("arguments")
            if tool not in REPLAY_SAFE_TOOLS:
                results.append(
                    ReplayItem(step, tool, call_id, "skipped", reason="tool is not replay-safe")
                )
                continue
            if not isinstance(arguments, dict):
                results.append(
                    ReplayItem(step, tool, call_id, "skipped", reason="arguments were not persisted")
                )
                continue

            decision = replay_ctx.policy_engine.evaluate_tool(tool, arguments)
            if not decision.allowed:
                results.append(
                    ReplayItem(step, tool, call_id, "skipped", reason=decision.reason)
                )
                continue
            if decision.requires_approval:
                results.append(
                    ReplayItem(step, tool, call_id, "skipped", reason="replay requires approval")
                )
                continue

            handler = self.registry.handler(tool)
            if handler is None:
                results.append(
                    ReplayItem(step, tool, call_id, "skipped", reason="tool is not registered")
                )
                continue
            started = time.perf_counter()
            try:
                output = await handler(arguments, replay_ctx)
                text = str(output or "")
                results.append(
                    ReplayItem(
                        step,
                        tool,
                        call_id,
                        "ok",
                        duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                        output=text,
                        output_sha256=self._hash(text),
                    )
                )
            except Exception as exc:
                results.append(
                    ReplayItem(
                        step,
                        tool,
                        call_id,
                        "error",
                        duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                        reason=str(exc),
                    )
                )
        return results
