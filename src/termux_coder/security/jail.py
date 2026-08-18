from __future__ import annotations

import os
from pathlib import Path


class JailViolation(Exception):
    """Raised when a path access violates workspace boundary rules."""


class WorkspaceJail:
    """
    Workspace Jail آمن:
    resolve() ثم is_relative_to() — وليس startswith().

    الضمانات:
    - يمنع /project2 عندما يكون الـ workspace هو /project
    - يمنع مسارات ../
    - يمنع symlinks الهاربة (لأن resolve() يتبعها)
    - يمنع أجهزة خاصة ومجلدات عند استخدام check_readable
    """

    def __init__(self, root: Path):
        self.root = root.resolve()
        if not self.root.is_dir():
            raise JailViolation(f"workspace root is not a directory: {root}")

    # ── التحقق الأساسي من المسار ──────────────────────────

    def check(self, user_path: str | Path) -> Path:
        """
        تحقق من أن المسار داخل الـ workspace وأعد المسار المطلق المُحلَّل.
        يقبل المسارات النسبية والمطلقة، لكن يرفض كل ما يقع خارج الجذر.
        """
        p = Path(user_path).expanduser()
        if not p.is_absolute():
            p = self.root / p
        p = p.resolve()
        if not p.is_relative_to(self.root):
            raise JailViolation(
                f"path outside workspace: {user_path!r} → {p} "
                f"(workspace: {self.root})"
            )
        return p

    def check_readable(self, user_path: str | Path) -> Path:
        """
        تحقق من المسار ثم تأكد أنه:
        - موجود
        - ملف عادي (ليس مجلداً أو رابطاً رمزياً هارباً أو جهازاً)
        - قابل للقراءة
        يرفض الملفات الثنائية (null bytes في أول 8192 بايت).
        """
        p = self.check(user_path)
        if not p.exists():
            raise JailViolation(f"path does not exist: {user_path!r}")
        if p.is_dir():
            raise JailViolation(f"path is a directory, not a file: {user_path!r}")
        if not p.is_file():
            # جهاز خاص، socket، pipe، إلخ
            raise JailViolation(
                f"path is not a regular file: {user_path!r} "
                f"(mode: {oct(p.stat().st_mode)})"
            )
        # فحص ثنائي (null bytes)
        try:
            with p.open("rb") as fh:
                chunk = fh.read(8192)
            if b"\x00" in chunk:
                raise JailViolation(
                    f"refusing to read binary file: {user_path!r}"
                )
        except PermissionError as exc:
            raise JailViolation(f"permission denied reading: {user_path!r}") from exc
        return p

    def check_writable_dir(self, user_path: str | Path) -> Path:
        """
        تحقق من أن مسار الكتابة (أو مجلده الأب) داخل الـ workspace.
        يُستخدم قبل إنشاء ملفات جديدة.
        """
        p = self.check(user_path)
        parent = p.parent
        # تحقق من أن المجلد الأب أيضاً داخل الـ workspace
        parent_resolved = parent.resolve()
        if not parent_resolved.is_relative_to(self.root):
            raise JailViolation(
                f"parent directory outside workspace: {parent} "
                f"(workspace: {self.root})"
            )
        return p

    # ── مساعدات ──────────────────────────────────────────

    def rel(self, p: Path) -> str:
        """أعد المسار النسبي من الجذر. يرفع ValueError إذا لم يكن داخل الجذر."""
        return str(p.relative_to(self.root))

    def safe_rel(self, p: Path, default: str = ".") -> str:
        """أعد المسار النسبي أو القيمة الافتراضية دون استثناء."""
        try:
            return str(p.relative_to(self.root))
        except ValueError:
            return default

    def exists_in_workspace(self, user_path: str | Path) -> bool:
        """تحقق من وجود المسار داخل الـ workspace دون استثناء."""
        try:
            p = self.check(user_path)
            return p.exists()
        except JailViolation:
            return False
