from __future__ import annotations

import ast
import logging
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

from ..security.jail import WorkspaceJail

_log = logging.getLogger(__name__)

# Resolve git binary once at import time to avoid partial-path lookup (B607)
_GIT_BIN: str | None = shutil.which("git")

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", ".termux_coder",
    ".cache", "dist", "build", ".next", "target",
}
MAX_FILES = 400
MAX_SCAN_BYTES = 200_000
MAX_NAMES = 600

KIND_WEIGHT = {
    "class": 3, "struct": 3, "type": 3,
    "def": 2, "function": 2,
    "method": 1,
}

EXT_LANG = {
    ".py": "python",
    ".js": "js", ".jsx": "js", ".ts": "js", ".tsx": "js",
    ".go": "go", ".rs": "rust", ".sh": "sh",
}

GENERIC_PATTERNS = {
    "js": [
        ("class", re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)")),
        ("function", re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)")),
        ("method", re.compile(r"^\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{", re.M)),
    ],
    "go": [
        ("type", re.compile(r"\btype\s+([A-Za-z_][\w]*)")),
        ("function", re.compile(r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)")),
    ],
    "rust": [
        ("struct", re.compile(r"\bstruct\s+([A-Za-z_][\w]*)")),
        ("function", re.compile(r"\bfn\s+([A-Za-z_][\w]*)")),
    ],
    "sh": [
        ("function", re.compile(r"^\s*(?:function\s+)?([A-Za-z_][\w]*)\s*\(\)", re.M)),
    ],
}


class RepoMap:
    """
    خريطة مستودع خفيفة:
    مسح → استخراج رموز (AST لبايثون، regex للباقي) → ترتيب بالمرجعية → ضغط بميزانية رموز.
    """

    def __init__(self, jail: WorkspaceJail, budget_chars: int = 6000):
        self.jail = jail
        self.budget = budget_chars
        self.last_stats = {"files": 0, "symbols": 0}
        self.changed = False
        self._sig: int | None = None
        self._symbols: list[tuple[str, str, str, int, int]] = []
        self._parse_errors: list[tuple[str, str]] = []

    # ── جمع الملفات ────────────────────────────────────────
    def _collect_files(self) -> list[Path]:
        root = self.jail.root
        try:
            if _GIT_BIN is None:
                raise FileNotFoundError("git executable not found in PATH")
            proc = subprocess.run(
                [_GIT_BIN, "ls-files"], cwd=root, capture_output=True, text=True, timeout=10
            )
            if proc.returncode == 0:
                paths = []
                for rel in proc.stdout.splitlines():
                    p = root / rel
                    if p.suffix in EXT_LANG and p.is_file():
                        paths.append(p)
                    if len(paths) >= MAX_FILES:
                        break
                return paths
        except (OSError, TimeoutError, FileNotFoundError) as exc:
            _log.debug("repo-map git fallback: %s", type(exc).__name__)

        paths = []
        for p in sorted(root.rglob("*")):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if p.is_file() and p.suffix in EXT_LANG:
                paths.append(p)
            if len(paths) >= MAX_FILES:
                break
        return paths

    # ── استخراج الرموز ──────────────────────────────────────
    @staticmethod
    def _py_symbols(text: str) -> list[tuple[str, str, int]]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        out: list[tuple[str, str, int]] = []

        def walk(node, prefix: str) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    q = f"{prefix}{child.name}"
                    out.append(("class", q, child.lineno))
                    walk(child, q + ".")
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    kind = "method" if prefix else "def"
                    out.append((kind, f"{prefix}{child.name}", child.lineno))
                else:
                    walk(child, prefix)

        walk(tree, "")
        return out

    def _generic_symbols(self, lang: str, text: str) -> list[tuple[str, str, int]]:
        out = []
        for kind, rx in GENERIC_PATTERNS.get(lang, []):
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                out.append((kind, m.group(1), line))
        return out

    # ── البناء مع التخزين المؤقت ─────────────────────────────
    @staticmethod
    def _signature(files: list[Path]) -> int:
        sig = []
        for p in files:
            try:
                sig.append((str(p), int(p.stat().st_mtime)))
            except OSError:
                sig.append((str(p), 0))
        return hash(tuple(sig))

    def _build(self) -> None:
        self.changed = False
        files = self._collect_files()
        sig = self._signature(files)
        if sig == self._sig and self._symbols:
            return
        self._sig = sig
        self.changed = True
        self._parse_errors = []

        root = self.jail.root
        texts: dict[Path, str] = {}
        raw: list[tuple[str, str, str, int]] = []

        for p in files:
            try:
                if p.stat().st_size > MAX_SCAN_BYTES:
                    continue
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            texts[p] = text
            lang = EXT_LANG[p.suffix]
            rel = p.relative_to(root).as_posix()
            if lang == "python":
                try:
                    ast.parse(text)
                except SyntaxError as exc:
                    location = f"line {exc.lineno}" if exc.lineno else "unknown line"
                    self._parse_errors.append((rel, f"syntax error at {location}"))
                    continue
                syms = self._py_symbols(text)
            else:
                syms = self._generic_symbols(lang, text)
            raw.extend((rel, kind, name, line) for kind, name, line in syms)

        # ترتيب بالمرجعية: عدّ الاستشهادات عبر المشروع كله
        leaves = {name.rsplit(".", 1)[-1] for _, _, name, _ in raw}
        names = [n for n in leaves if len(n) >= 3]
        names = sorted(names, key=lambda n: (-len(n), n))[:MAX_NAMES]

        refs: Counter = Counter()
        if names:
            big = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b")
            for text in texts.values():
                refs.update(m.group() for m in big.finditer(text))

        scored = []
        for rel, kind, name, line in raw:
            leaf = name.rsplit(".", 1)[-1]
            score = refs.get(leaf, 0) * 2 + KIND_WEIGHT.get(kind, 1)
            scored.append((rel, kind, name, line, score))

        self._symbols = scored
        self.last_stats = {
            "files": len(texts),
            "symbols": len(scored),
            "parse_errors": len(self._parse_errors),
        }

    # ── العرض ──────────────────────────────────────────────
    def _sorted_symbols(self):
        return sorted(self._symbols, key=lambda s: (-s[4], s[0], s[3]))

    def render_budget(self) -> str:
        self._build()
        return self._render(self._sorted_symbols(), self.budget)

    def render_full(self, focus: str = "", refresh: bool = False) -> str:
        if refresh:
            self._sig = None
        self._build()
        syms = self._sorted_symbols()
        if focus:
            f = focus.lower()
            syms = [s for s in syms if f in s[0].lower() or f in s[2].lower()]
        return self._render(syms, 20_000)

    def _render(self, syms, budget: int) -> str:
        out: list[str] = []
        used = 0
        current_file = None
        for rel, kind, name, line, score in syms:
            parts = []
            if rel != current_file:
                parts.append(f"{rel}:")
                current_file = rel
            indent = "    " if "." in name else "  "
            parts.append(f"{indent}{kind} {name}")
            
            text = "\n".join(parts)
            cost = len(text) + 1
            if used + cost > budget:
                break
            out.append(text)
            used += cost
        if self._parse_errors:
            if out:
                out.append("")
            out.append("Diagnostics:")
            out.extend(f"  {path}: {message}" for path, message in self._parse_errors)
        return "\n".join(out)
