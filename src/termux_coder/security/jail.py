from __future__ import annotations

from pathlib import Path


class JailViolation(Exception):
    pass


class WorkspaceJail:
    """
    Workspace Jail آمن:
    resolve() ثم is_relative_to() — وليس startswith().
    يمنع /project2 عندما يكون الـ workspace هو /project،
    ويمنع ../ ويمنع symlinks الهاربة (لأن resolve() يتبعها).
    """

    def __init__(self, root: Path):
        self.root = root.resolve()

    def check(self, user_path: str | Path) -> Path:
        p = Path(user_path).expanduser()
        if not p.is_absolute():
            p = self.root / p
        p = p.resolve()
        if not p.is_relative_to(self.root):
            raise JailViolation(f"path outside workspace: {user_path}")
        return p

    def rel(self, p: Path) -> str:
        return str(p.relative_to(self.root))
