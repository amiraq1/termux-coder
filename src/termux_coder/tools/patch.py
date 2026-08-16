from __future__ import annotations

import difflib

SEARCH_MARK = "<<<<<<< SEARCH"
DIVIDER = "======="
REPLACE_MARK = ">>>>>>> REPLACE"


class PatchError(Exception):
    pass


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


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def apply_blocks(source: str, blocks: list[tuple[str, str]]) -> str:
    source = _norm(source)
    for find, replace in blocks:
        find = _norm(find)
        replace = _norm(replace)
        if find == "":
            raise PatchError("empty SEARCH block on an existing file")
        count = source.count(find)
        if count == 0:
            raise PatchError("SEARCH block not found; include more surrounding context")
        if count > 1:
            raise PatchError("SEARCH block is ambiguous; include more surrounding context")
        source = source.replace(find, replace, 1)
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
