"""Identifiers and metadata for grouping one user request and its execution trace."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import uuid
from collections.abc import Iterable


_SPACE_RE = re.compile(r"\s+")


def _normalize_request(text: str) -> str:
    return _SPACE_RE.sub(" ", str(text or "").strip()).casefold()


@dataclass(frozen=True, slots=True)
class TurnBundle:
    """Immutable identity shared by one request and all of its execution messages."""

    turn_id: str
    task_id: str
    related_paths: tuple[str, ...] = ()

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

    def add_paths(self, paths: Iterable[str]) -> "TurnBundle":
        normalized = {
            str(path).replace("\\", "/").strip()
            for path in paths
            if isinstance(path, str) and path.strip()
        }
        normalized = {
            path for path in normalized
            if not path.startswith("/") and path != "." and ".." not in path.split("/")
        }
        return TurnBundle(
            turn_id=self.turn_id,
            task_id=self.task_id,
            related_paths=tuple(sorted(set(self.related_paths) | normalized)),
        )

    def metadata(self) -> dict[str, object]:
        return {
            "turn_id": self.turn_id,
            "task_id": self.task_id,
            "related_paths": list(self.related_paths),
        }


def bundle_metadata(message: dict) -> dict[str, object]:
    """Extract valid bundle metadata from an in-memory message."""
    metadata: dict[str, object] = {}
    for key in ("turn_id", "task_id"):
        value = message.get(key)
        if isinstance(value, str) and value:
            metadata[key] = value
    paths = message.get("related_paths")
    if isinstance(paths, (list, tuple, set)):
        valid_paths = sorted(
            {
                str(path).replace("\\", "/").strip()
                for path in paths
                if isinstance(path, str)
                and path.strip()
                and not path.startswith("/")
                and path != "."
                and ".." not in path.split("/")
            }
        )
        if valid_paths:
            metadata["related_paths"] = valid_paths
    return metadata
