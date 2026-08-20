from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

from .context import SessionState


class SessionStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at REAL,
                updated_at REAL,
                workspace TEXT,
                model TEXT,
                title TEXT
            );
            CREATE TABLE IF NOT EXISTS messages (
                session_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                extra TEXT,
                PRIMARY KEY (session_id, seq)
            );
            CREATE TABLE IF NOT EXISTS state (
                session_id TEXT PRIMARY KEY,
                read_files TEXT,
                applied_patches TEXT,
                todos TEXT,
                research_intent TEXT,
                research_packet TEXT
            );
            """
        )
        self._ensure_state_column("research_intent")
        self._ensure_state_column("research_packet")
        self.conn.commit()

    def _ensure_state_column(self, column: str) -> None:
        columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(state)").fetchall()
        }
        if column not in columns:
            self.conn.execute(f"ALTER TABLE state ADD COLUMN {column} TEXT")

    # ── جلسات ─────────────────────────────────────────────
    def create(self, workspace: str, model: str, title: str = "") -> str:
        sid = uuid.uuid4().hex[:12]
        now = time.time()
        self.conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?)",
            (sid, now, now, workspace, model, title),
        )
        self.conn.commit()
        return sid

    def get(self, sid: str):
        cur = self.conn.execute(
            "SELECT id, workspace, model, title FROM sessions WHERE id=?", (sid,)
        )
        r = cur.fetchone()
        return (
            {"id": r[0], "workspace": r[1], "model": r[2], "title": r[3]}
            if r
            else None
        )

    def touch(self, sid: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?", (time.time(), sid)
        )
        self.conn.commit()

    def set_title(self, sid: str, title: str) -> None:
        self.conn.execute("UPDATE sessions SET title=? WHERE id=?", (title, sid))
        self.conn.commit()

    def list_recent(self, limit: int = 10):
        cur = self.conn.execute(
            "SELECT id, updated_at, workspace, model, title FROM sessions "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        return [
            {"id": r[0], "updated_at": r[1], "workspace": r[2], "model": r[3], "title": r[4]}
            for r in cur.fetchall()
        ]

    # ── رسائل ─────────────────────────────────────────────
    def save_message(self, sid: str, seq: int, message: dict) -> None:
        extra = {}
        if message.get("tool_calls"):
            extra["tool_calls"] = message["tool_calls"]
        if message.get("tool_call_id"):
            extra["tool_call_id"] = message["tool_call_id"]
        for key in ("turn_id", "task_id"):
            if isinstance(message.get(key), str) and message[key]:
                extra[key] = message[key]
        self.conn.execute(
            "INSERT OR REPLACE INTO messages (session_id, seq, role, content, extra) "
            "VALUES (?,?,?,?,?)",
            (
                sid,
                seq,
                message.get("role", ""),
                message.get("content"),
                json.dumps(extra) if extra else None,
            ),
        )
        self.conn.commit()

    def load_messages(self, sid: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT role, content, extra FROM messages WHERE session_id=? ORDER BY seq",
            (sid,),
        )
        out = []
        for role, content, extra in cur.fetchall():
            m = {"role": role, "content": content or ""}
            if extra:
                m.update(json.loads(extra))
            out.append(m)
        return _sanitize(out)

    # ── حالة ──────────────────────────────────────────────
    def save_state(self, sid: str, state: SessionState) -> None:
        # احتفظ بآخر 50 ترقيع فقط تفادياً لتراكم البيانات
        patches_to_save = state.applied_patches[-50:] if state.applied_patches else []
        self.conn.execute(
            "INSERT OR REPLACE INTO state "
            "(session_id, read_files, applied_patches, todos, research_intent, research_packet) "
            "VALUES (?,?,?,?,?,?)",
            (
                sid,
                json.dumps(sorted(state.read_files)),
                json.dumps(patches_to_save),
                json.dumps(state.todos),
                json.dumps(state.research_intent) if state.research_intent is not None else None,
                json.dumps(state.research_packet) if state.research_packet is not None else None,
            ),
        )
        self.conn.commit()

    def load_state(self, sid: str) -> SessionState | None:
        cur = self.conn.execute(
            "SELECT read_files, applied_patches, todos, research_intent, research_packet "
            "FROM state WHERE session_id=?",
            (sid,),
        )
        r = cur.fetchone()
        if not r:
            return None
        # Migrate: applied_patches may be list[str] (old) or list[dict] (new)
        raw_patches = json.loads(r[1] or "[]")
        migrated_patches: list[dict] = []
        for p in raw_patches:
            if isinstance(p, str):
                # old format: just the path string
                migrated_patches.append({"path": p, "backup": None, "old_hash": None, "new_hash": None, "ts": None})
            elif isinstance(p, dict):
                migrated_patches.append(p)
        return SessionState(
            read_files=set(json.loads(r[0] or "[]")),
            applied_patches=migrated_patches,
            todos=json.loads(r[2] or "[]"),
            research_intent=json.loads(r[3]) if r[3] else None,
            research_packet=json.loads(r[4]) if r[4] else None,
        )

    def close(self) -> None:
        self.conn.close()


def _sanitize(messages: list[dict]) -> list[dict]:
    """
    قتل الوكيل وسط جولة يترك ذيلًا معلّقًا:
    assistant بـ tool_calls بدون نتائج أدوات.
    نحذفه حتى يبقى العقد مع الـ API سليمًا عند الاستئناف.
    """
    while (
        messages
        and messages[-1].get("role") == "assistant"
        and messages[-1].get("tool_calls")
    ):
        messages.pop()
    return messages
