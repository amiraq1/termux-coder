from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextItem:
    """
    عنصر سياق قابل للأولوية والضغط.
    
    priority:
        P0 = system prompt, current user request
        P1 = active file, current LSP, current tool call, current patch
        P2 = recent messages, recent tool results
        P3 = repo map, git status
        P4 = old tool results
        P5 = old conversation
    
    compressible:
        هل يمكن ضغطه؟ (P0, P1 = False عادة)
    
    persistent:
        هل يبقى عبر الجلسات؟ (system prompt = True)
    """

    content: str
    kind: str  # "system", "user", "assistant", "tool", "map", "lsp", "git", "file", "summary"
    priority: int  # 0-5
    compressible: bool = True
    persistent: bool = False
    source_messages: list[int] = field(default_factory=list)  # للملخصات
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.priority < 0 or self.priority > 5:
            raise ValueError(f"priority must be 0-5, got {self.priority}")


class PriorityEngine:
    """تحديد أولوية العناصر بناءً على السياق الحالي."""

    @staticmethod
    def classify(message: dict, seq: int, current_seq: int) -> ContextItem:
        """تصنيف رسالة إلى ContextItem بأولوية مناسبة."""
        role = message.get("role", "")
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls")
        tool_call_id = message.get("tool_call_id")

        # P0: system prompt
        if role == "system":
            return ContextItem(
                content=content,
                kind="system",
                priority=0,
                compressible=False,
                persistent=True,
            )

        # P0: user request حالي (آخر user message)
        if role == "user":
            distance = current_seq - seq
            if distance <= 1:
                return ContextItem(
                    content=content,
                    kind="user",
                    priority=0,
                    compressible=False,
                )
            else:
                # محادثة قديمة
                return ContextItem(
                    content=content,
                    kind="user",
                    priority=5,
                    compressible=True,
                )

        # P1: tool call حالي
        if role == "assistant" and tool_calls:
            return ContextItem(
                content=content,
                kind="assistant",
                priority=1,
                compressible=False,
                metadata={"tool_calls": tool_calls},
            )

        # P2: tool result حديث
        if role == "tool":
            distance = current_seq - seq
            if distance <= 5:
                return ContextItem(
                    content=content,
                    kind="tool",
                    priority=2,
                    compressible=True,
                    metadata={"tool_call_id": tool_call_id},
                )
            else:
                # tool result قديم
                return ContextItem(
                    content=content,
                    kind="tool",
                    priority=4,
                    compressible=True,
                    metadata={"tool_call_id": tool_call_id},
                )

        # P2: assistant reply حديث
        if role == "assistant":
            distance = current_seq - seq
            if distance <= 5:
                return ContextItem(
                    content=content,
                    kind="assistant",
                    priority=2,
                    compressible=True,
                )
            else:
                return ContextItem(
                    content=content,
                    kind="assistant",
                    priority=5,
                    compressible=True,
                )

        # fallback
        return ContextItem(
            content=content,
            kind=role,
            priority=3,
            compressible=True,
        )
