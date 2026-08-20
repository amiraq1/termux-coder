"""Identifiers and metadata for grouping one user request and its execution trace."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import uuid


_SPACE_RE = re.compile(r"\s+")


def _normalize_request(text: str) -> str:
    return _SPACE_RE.sub(" ", str(text or "").strip()).casefold()


@dataclass(frozen=True, slots=True)
class TurnBundle:
    """Immutable identity shared by one request and all of its execution messages."""

    turn_id: str
    task_id: str

    @classmethod
    def create(cls, user_text: str, session_id: str | None = None) -> "TurnBundle":
        """Create a per-execution turn and a stable task fingerprint.

        The task id is a digest of session identity plus normalized request text;
        raw user text is never embedded in the identifier.
        """
        turn_id = uuid.uuid4().hex[:12]
        scope = f"{session_id or ''}\x00{_normalize_request(user_text)}"
        task_id = f"task-{hashlib.sha256(scope.encode('utf-8')).hexdigest()[:16]}"
        return cls(turn_id=turn_id, task_id=task_id)

    def metadata(self) -> dict[str, str]:
        return {"turn_id": self.turn_id, "task_id": self.task_id}


def bundle_metadata(message: dict) -> dict[str, str]:
    """Extract valid bundle identifiers from an in-memory message."""
    metadata: dict[str, str] = {}
    for key in ("turn_id", "task_id"):
        value = message.get(key)
        if isinstance(value, str) and value:
            metadata[key] = value
    return metadata
