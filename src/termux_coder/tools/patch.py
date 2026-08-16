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


def recover_simple_patch(patch_text: str, source: str):
    """
    استرداد patch بلا علامات SEARCH/REPLACE:
    - فكّ هروب \\n الحرفية إذا لم توجد أسطر فعلية
    - نتيجته سطران تمامًا، والأول موجود بشكل فريد في الملف
      → (find, replace)
    وإلا → None (نرفض بأمان بدل التخمين)
    """
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
