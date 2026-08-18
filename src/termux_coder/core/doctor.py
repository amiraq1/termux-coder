from __future__ import annotations

import shutil
import sqlite3
import sys
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib
from pathlib import Path

from .. import logo
from ..config import Settings
from ..security.jail import WorkspaceJail, JailViolation
from .verification import VerificationRunner


def _ok(label: str, detail: str = "") -> None:
    print(f"  [✓] {label}" + (f" — {detail}" if detail else ""))


def _warn(label: str, detail: str = "") -> None:
    print(f"  [!] {label}" + (f" — {detail}" if detail else ""))


def _fail(label: str, detail: str = "") -> None:
    print(f"  [✗] {label}" + (f" — {detail}" if detail else ""))


def run_doctor(settings: Settings) -> int:
    logo.print_banner()
    problems = 0

    # 1) بايثون
    v = sys.version_info
    if v >= (3, 10):
        _ok(f"python {v.major}.{v.minor}.{v.micro}")
    else:
        _fail("python", "يلزم >= 3.10"); problems += 1

    # 2) التبعيات
    for mod in ("textual", "openai"):
        try:
            __import__(mod)
            _ok(mod)
        except Exception:
            _fail(mod, "pip install textual openai"); problems += 1

    # 3) الأدوات الثنائية
    for binary, hint in [
        ("git", "pkg install git"),
        ("grep", "pkg install grep"),
        ("node", "اختياري: pkg install nodejs (MCP)"),
        ("pylsp", "اختياري: pip install python-lsp-server (LSP)"),
    ]:
        if shutil.which(binary):
            _ok(binary)
        elif hint.startswith("اختياري"):
            _warn(binary, hint)
        else:
            _fail(binary, hint); problems += 1

    # 4) بيانات الاعتماد (دروس 401 و ascii)
    key = settings.openai_api_key
    if key and key != "EMPTY" and key.isascii():
        _ok("api key", "present (ASCII-valid)")
    else:
        _fail("api key", "حرّر ~/termux-coder/env_nvidia.sh باقتباسات إنجليزية ثم source ~/.bashrc")
        problems += 1
    _ok("base url", settings.openai_base_url)
    _ok("model", settings.model)

    # 5) مساحة العمل
    ws = settings.workspace.resolve()
    if ws.exists():
        _ok("workspace", str(ws))
    else:
        _fail("workspace", "المجلد غير موجود"); problems += 1
    if ws == Path.home():
        _warn("workspace = home", "يُفضّل مجلد مشروع مستقل")
    try:
        WorkspaceJail(ws)
        _ok("workspace jail", "path resolution is inside workspace")
    except (JailViolation, OSError) as exc:
        _fail("workspace jail", str(exc)); problems += 1

    # 6) إعداد التحقق: parse فقط، دون تنفيذ الأمر
    verification_path = ws / ".termux-coder.toml"
    if not verification_path.exists():
        _warn("verification config", "not configured; verification will be skipped")
    else:
        runner = VerificationRunner(ws, settings)
        argv, reason = runner._load_argv()
        if argv is None:
            _fail("verification config", reason); problems += 1
        else:
            _ok("verification config", f"valid and allowlisted (not executed): {' '.join(argv)}")

    # 7) قاعدة الجلسات (sqlite + WAL)
    try:
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        db = settings.state_dir / "doctor.db"
        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS t(x)")
        conn.close()
        db.unlink(missing_ok=True)
        _ok("sessions db (sqlite/WAL)")
    except Exception as e:
        _fail("sqlite/WAL", str(e)); problems += 1

    # 8) Termux:API (اختياري)
    if shutil.which("termux-notification"):
        _ok("termux-api")
    else:
        _warn("termux-api", "اختياري: pkg install termux-api")

    print()
    if problems == 0:
        logo.ctrl("doctor", "كل شيء سليم — جاهز للإقلاع")
    else:
        logo.ctrl("doctor", f"{problems} مشكلة تحتاج إصلاحًا")
    return 1 if problems else 0
