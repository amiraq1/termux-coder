"""Deterministic, bounded impact analysis for coding tasks.

The analyzer is deliberately conservative: AST-backed references are marked
confirmed only when imports make the target relationship explicit. Textual
matches and dynamic-loading patterns are reported separately instead of being
presented as complete call-graph facts.
"""
from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


_DYNAMIC_MARKERS = (
    "getattr(",
    "import_module(",
    "__import__(",
    "entry_points(",
    "pkg_resources",
    "importlib.",
)

_SKIP_DIRS = {".git", ".termux_coder", ".venv", "venv", "node_modules", "__pycache__"}
_PATH_PATTERN = re.compile(r"(?<![\w./-])(?:[\w.-]+/)*[\w.-]+\.(?:py|pyi|js|jsx|ts|tsx|rs|go|java|rb|php)\b")
_SYMBOL_PATTERN = re.compile(
    r"(?:function|class|method|symbol|دالة|كلاس|رمز)\s+([A-Za-z_]\w*)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ImpactReference:
    path: str
    line: int
    symbol: str | None
    reason: str


@dataclass(frozen=True)
class ImpactReport:
    target: str
    direct_files: tuple[str, ...]
    confirmed_callers: tuple[ImpactReference, ...]
    possible_references: tuple[ImpactReference, ...]
    unknown_dynamic_references: tuple[ImpactReference, ...]
    confidence: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        for key in (
            "direct_files",
            "confirmed_callers",
            "possible_references",
            "unknown_dynamic_references",
        ):
            if key in payload and isinstance(payload[key], tuple):
                payload[key] = list(payload[key])
        return payload


def extract_target(text: str) -> tuple[str, str | None] | None:
    """Extract an explicit source path and optional symbol from user text."""
    path_match = _PATH_PATTERN.search(text)
    if path_match is None:
        return None
    symbol_match = _SYMBOL_PATTERN.search(text)
    return path_match.group(0), symbol_match.group(1) if symbol_match else None


class ImpactAnalyzer:
    """Analyze a bounded Python workspace without executing project code."""

    def __init__(self, root: Path, *, max_files: int = 500, max_file_chars: int = 120_000):
        self.root = root.resolve()
        self.max_files = max_files
        self.max_file_chars = max_file_chars

    def analyze(self, path: str, symbol: str | None = None) -> ImpactReport:
        target_path = self._safe_path(path)
        target_rel = target_path.relative_to(self.root).as_posix()
        target = f"{target_rel}::{symbol}" if symbol else target_rel
        confirmed: list[ImpactReference] = []
        possible: list[ImpactReference] = []
        dynamic: list[ImpactReference] = []

        if not target_path.is_file():
            return ImpactReport(
                target=target,
                direct_files=(target_rel,),
                confirmed_callers=(),
                possible_references=(),
                unknown_dynamic_references=(),
                confidence="low",
            )

        target_module = target_path.stem
        candidates = list(self._python_files())[: self.max_files]
        for candidate in candidates:
            if candidate == target_path:
                continue
            try:
                source = candidate.read_text(encoding="utf-8")[: self.max_file_chars]
            except (OSError, UnicodeError):
                continue
            rel = candidate.relative_to(self.root).as_posix()

            if symbol and any(marker in source for marker in _DYNAMIC_MARKERS):
                for line_no, line in enumerate(source.splitlines(), start=1):
                    if symbol in line and any(marker in line for marker in _DYNAMIC_MARKERS):
                        dynamic.append(
                            ImpactReference(rel, line_no, None, "dynamic import or attribute lookup")
                        )

            if not symbol:
                continue

            confirmed_lines = self._confirmed_call_lines(
                source, target_module=target_module, symbol=symbol
            )
            confirmed_line_numbers = {line for line, _ in confirmed_lines}
            for line_no, caller in confirmed_lines:
                confirmed.append(
                    ImpactReference(rel, line_no, caller, "explicit import and call")
                )

            for line_no, line in enumerate(source.splitlines(), start=1):
                if line_no in confirmed_line_numbers:
                    continue
                if re.search(rf"\b{re.escape(symbol)}\b", line):
                    possible.append(
                        ImpactReference(rel, line_no, None, "textual symbol reference")
                    )

        confidence = "high"
        if dynamic or possible:
            confidence = "medium"
        if not target_path.is_file() or len(candidates) >= self.max_files:
            confidence = "low"

        return ImpactReport(
            target=target,
            direct_files=(target_rel,),
            confirmed_callers=tuple(self._dedupe(confirmed)),
            possible_references=tuple(self._dedupe(possible)),
            unknown_dynamic_references=tuple(self._dedupe(dynamic)),
            confidence=confidence,
        )

    def _safe_path(self, path: str) -> Path:
        candidate = (self.root / path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("impact target escapes workspace")
        return candidate

    def _python_files(self) -> Iterable[Path]:
        for candidate in self.root.rglob("*.py"):
            if any(part in _SKIP_DIRS for part in candidate.parts):
                continue
            yield candidate

    @staticmethod
    def _confirmed_call_lines(source: str, *, target_module: str, symbol: str) -> list[tuple[int, str | None]]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        imported_names: set[str] = set()
        module_aliases: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                module_name = node.module.rsplit(".", 1)[-1]
                if module_name == target_module:
                    for item in node.names:
                        if item.name == symbol:
                            imported_names.add(item.asname or item.name)
            elif isinstance(node, ast.Import):
                for item in node.names:
                    imported_module = item.name.rsplit(".", 1)[-1]
                    if imported_module == target_module:
                        module_aliases.add(item.asname or imported_module)

        hits: list[tuple[int, str | None]] = []
        caller_stack: list[str | None] = []

        class Visitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                caller_stack.append(node.name)
                self.generic_visit(node)
                caller_stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, node):
                matches = False
                if isinstance(node.func, ast.Name):
                    matches = node.func.id in imported_names
                elif isinstance(node.func, ast.Attribute):
                    matches = (
                        node.func.attr == symbol
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id in module_aliases
                    )
                if matches:
                    hits.append((node.lineno, caller_stack[-1] if caller_stack else None))
                self.generic_visit(node)

        Visitor().visit(tree)
        return hits

    @staticmethod
    def _dedupe(items: list[ImpactReference]) -> list[ImpactReference]:
        seen: set[tuple] = set()
        result: list[ImpactReference] = []
        for item in items:
            key = (item.path, item.line, item.symbol, item.reason)
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result
