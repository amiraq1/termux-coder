from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    """
    سجل تدقيق منظّم بطوابع زمنية UTC واعية بالمنطقة الزمنية.

    التنسيق: JSONL — سطر JSON واحد لكل حدث.
    الحقول الثابتة: ts_utc (ISO 8601), event
    الحقول الاختيارية: session_id, tool, path, hash, reason, ...
    """

    def __init__(self, path: Path, session_id: str | None = None):
        self.path = path
        self.session_id = session_id
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **data) -> None:
        """سجّل حدثًا مع طابع زمني UTC دقيق."""
        record: dict = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event": event,
        }
        if self.session_id:
            record["session_id"] = self.session_id
        record.update(data)
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # عدم إيقاف العمليات بسبب فشل السجل

    def tail(self, n: int = 50) -> list[dict]:
        """أعد آخر n حدث من السجل."""
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        records = []
        for line in lines[-n:]:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return records

