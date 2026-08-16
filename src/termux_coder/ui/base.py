from __future__ import annotations

from contextlib import nullcontext
from typing import Any


class AgentUI:
    """عقد واجهة الوكيل: CLI و TUI يطبقان نفس العقد."""

    def thinking(self):
        return nullcontext()

    async def on_token(self, text: str) -> None:
        pass

    async def on_event(self, kind: str, **payload: Any) -> None:
        pass

    async def request_approval(self, kind: str, payload: dict) -> bool:
        # الافتراضي رفض: fail-safe
        return False
