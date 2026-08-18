from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

SEARCH_MARK = "<<<<<<< SEARCH"
DIVIDER = "======="
REPLACE_MARK = ">>>>>>> REPLACE"


class PatchError(Exception):
    """Base error raised for invalid or unsafe patches."""


class PatchAmbiguityError(PatchError):
    """Raised when a SEARCH block can match more than one location."""


@dataclass(frozen=True)
class MatchResult:
    """A unique match selected by the smart matching engine."""

    line_start: int
    line_end: int
    confidence: float
    match_level: str
    start_offset: int = field(repr=False, compare=False, default=0)
    end_offset: int = field(repr=False, compare=False, default=0)


@dataclass(frozen=True)
class _Line:
    text: str
    start: int
    end: int


def parse_blocks(patch_text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    mode = None
    search: list[str] = []
    replace: list[str] = []

    for line in patch_text.splitlines():
        stripped = line.strip()
        if stripped == SEARCH_MARK:
            mode = "search"
            search, replace = [], []
            continue
        if stripped == DIVIDER and mode == "search":
            mode = "replace"
            continue
        if stripped == REPLACE_MARK and mode == "replace":
            blocks.append(("\n".join(search), "\n".join(replace)))
            mode = None
            continue
        if mode == "search":
            search.append(line)
        elif mode == "replace":
            replace.append(line)

    if mode is not None:
        raise PatchError("unterminated SEARCH/REPLACE block")
    if not blocks:
        raise PatchError("no SEARCH/REPLACE blocks found")
    return blocks


def recover_simple_patch(patch_text: str, source: str):
    """Recover a malformed two-line patch only when its SEARCH is unique."""
    text = patch_text
    if "\n" not in text and "\\n" in text:
        text = text.replace("\\n", "\n")

    lines = text.splitlines()
    if len(lines) != 2:
        return None

    find, replace = lines[0], lines[1]
    if not find or source.count(find) != 1:
        return None
    return find, replace


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _line_records(source: str) -> list[_Line]:
    records: list[_Line] = []
    offset = 0
    for part in source.splitlines(keepends=True):
        text = part[:-1] if part.endswith("\n") else part
        records.append(_Line(text=text, start=offset, end=offset + len(text)))
        offset += len(part)
    return records


def _line_numbers(source: str, start: int, end: int) -> tuple[int, int]:
    line_start = source.count("\n", 0, start) + 1
    last = max(start, end - 1)
    line_end = source.count("\n", 0, last) + 1
    return line_start, line_end


def _leading_width(line: str) -> tuple[int, str]:
    prefix = re.match(r"[ \t]*", line).group(0)
    width = len(prefix.expandtabs(8))
    return width, line[len(prefix):]


def _body_signature(line: str) -> str:
    _, body = _leading_width(line)
    return re.sub(r"[ \t]+", " ", body.rstrip())


def _whitespace_signature(line: str) -> tuple[int, str]:
    """Normalize intra-line whitespace while preserving absolute indentation."""
    width, body = _leading_width(line)
    return width, re.sub(r"[ \t]+", "", body.rstrip())


def _indentation_signature(lines: list[str]) -> tuple[tuple[int, str], ...]:
    widths = sorted({_leading_width(line)[0] for line in lines if line.strip()})
    levels = {width: index for index, width in enumerate(widths)}
    result: list[tuple[int, str]] = []
    for line in lines:
        width, _ = _leading_width(line)
        level = levels.get(width, 0)
        result.append((level, re.sub(r"[ \t]+", "", line.rstrip())))
    return tuple(result)


def _window_end(candidate_lines: list[_Line]) -> int:
    return candidate_lines[-1].end


def _line_matches(
    source: str,
    search: str,
    signature,
    confidence: float,
) -> list[tuple[int, int, float]]:
    source_lines = _line_records(source)
    search_lines = search.splitlines()
    if not search_lines or len(search_lines) > len(source_lines):
        return []

    wanted = tuple(signature(line) for line in search_lines)
    matches: list[tuple[int, int, float]] = []
    for index in range(len(source_lines) - len(search_lines) + 1):
        candidate_lines = source_lines[index : index + len(search_lines)]
        candidate = tuple(signature(line.text) for line in candidate_lines)
        if candidate == wanted:
            matches.append(
                (candidate_lines[0].start, _window_end(candidate_lines), confidence)
            )
    return matches


def _indentation_matches(source: str, search: str) -> list[tuple[int, int, float]]:
    source_lines = _line_records(source)
    search_lines = search.splitlines()
    if not search_lines or len(search_lines) > len(source_lines):
        return []

    wanted = _indentation_signature(search_lines)
    matches: list[tuple[int, int, float]] = []
    for index in range(len(source_lines) - len(search_lines) + 1):
        candidate_lines = source_lines[index : index + len(search_lines)]
        candidate = _indentation_signature([line.text for line in candidate_lines])
        if candidate == wanted:
            matches.append(
                (candidate_lines[0].start, _window_end(candidate_lines), 0.91)
            )
    return matches


def _context_matches(source: str, search: str) -> list[tuple[int, int, float]]:
    """Find a unique, high-similarity line window as a last-resort fallback."""
    source_lines = _line_records(source)
    search_lines = search.splitlines()
    if len(search_lines) < 2 or len(search_lines) > len(source_lines):
        return []

    wanted = "\n".join(_body_signature(line).strip() for line in search_lines)
    matches: list[tuple[int, int, float]] = []
    for index in range(len(source_lines) - len(search_lines) + 1):
        candidate_lines = source_lines[index : index + len(search_lines)]
        candidate = "\n".join(
            _body_signature(line.text).strip() for line in candidate_lines
        )
        score = difflib.SequenceMatcher(None, wanted, candidate, autojunk=False).ratio()
        if score >= 0.92:
            matches.append(
                (candidate_lines[0].start, _window_end(candidate_lines), score)
            )
    return matches


def _result(source: str, match: tuple[int, int, float], level: str) -> MatchResult:
    start, end, confidence = match
    line_start, line_end = _line_numbers(source, start, end)
    return MatchResult(
        line_start=line_start,
        line_end=line_end,
        confidence=round(confidence, 4),
        match_level=level,
        start_offset=start,
        end_offset=end,
    )


def smart_find_location(content: str, search_text: str) -> MatchResult:
    """Find one safe location using ordered matching strategies.

    The first strategy with candidates wins. A strategy yielding more than one
    candidate is rejected immediately; lower-confidence matches never
    disambiguate a higher-confidence strategy.
    """
    content = _norm(content)
    search_text = _norm(search_text)
    if not search_text:
        raise PatchError("empty SEARCH block on an existing file")

    exact: list[tuple[int, int, float]] = []
    cursor = 0
    while True:
        position = content.find(search_text, cursor)
        if position < 0:
            break
        exact.append((position, position + len(search_text), 1.0))
        cursor = position + max(1, len(search_text))

    strategies = (
        (exact, "exact"),
        (
            _line_matches(content, search_text, _whitespace_signature, 0.94),
            "whitespace-normalized",
        ),
        (_indentation_matches(content, search_text), "indentation-aware"),
        (_context_matches(content, search_text), "context-window"),
    )
    for matches, level in strategies:
        if len(matches) > 1:
            raise PatchAmbiguityError(
                "SEARCH block is ambiguous; include more surrounding context"
            )
        if matches:
            return _result(content, matches[0], level)

    raise PatchError("SEARCH block not found; include more surrounding context")


def apply_blocks(source: str, blocks: list[tuple[str, str]]) -> str:
    source = _norm(source)
    for find, replace in blocks:
        find = _norm(find)
        replace = _norm(replace)
        if find == "":
            raise PatchError("empty SEARCH block on an existing file")
        location = smart_find_location(source, find)
        source = source[: location.start_offset] + replace + source[location.end_offset :]
    return source


def make_diff(rel_path: str, old: str, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
            n=3,
        )
    )
