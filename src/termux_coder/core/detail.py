"""Deterministic detection of requests that benefit from detailed reports."""

from __future__ import annotations

import re


_DETAIL_MARKERS = (
    "repository",
    "repo",
    "codebase",
    "workspace",
    "project structure",
    "directory structure",
    "analyze the project",
    "analyse the project",
    "analyze the repository",
    "analyse the repository",
    "inspect the repository",
    "inspect the code",
    "review the code",
    "audit the code",
    "security audit",
    "architecture",
    "dependencies",
    "call graph",
    "map the repository",
    "repository map",
    "خريطة المستودع",
    "فحص المستودع",
    "تحليل المستودع",
    "تحليل المشروع",
    "بنية المشروع",
    "مراجعة الكود",
    "مراجعة المستودع",
    "تدقيق أمني",
)

_DETAIL_VERBS = (
    "analyze",
    "analyse",
    "inspect",
    "review",
    "audit",
    "explain",
    "map",
    "فحص",
    "حلل",
    "تحليل",
    "راجع",
    "مراجعة",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def wants_detailed_report(user_text: str) -> bool:
    """Return True for explicit repository/code-analysis requests.

    This gate is deterministic and turn-local. It never reads prior messages,
    tool results, or provider state, preventing detail-mode leakage between
    turns.
    """
    normalized = _normalize(user_text)
    if not normalized:
        return False
    if any(marker in normalized for marker in _DETAIL_MARKERS):
        return True
    has_detail_verb = any(verb in normalized for verb in _DETAIL_VERBS)
    has_scope = any(scope in normalized for scope in ("files", "functions", "modules", "المجلد", "الملفات", "الدوال"))
    return has_detail_verb and has_scope
