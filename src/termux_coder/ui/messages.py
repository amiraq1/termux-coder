from __future__ import annotations

from dataclasses import dataclass
from time import time


@dataclass(slots=True)
class MessageRecord:
    """Lightweight conversation metadata independent from rendered widgets."""

    message_id: int
    role: str
    text: str
    created_at: float
    has_code: bool = False

    @classmethod
    def create(cls, message_id: int, role: str, text: str) -> "MessageRecord":
        return cls(
            message_id=message_id,
            role=role,
            text=text,
            created_at=time(),
            has_code="```" in text,
        )
