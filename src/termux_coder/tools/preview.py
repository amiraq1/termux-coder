from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..core.context import SessionState
from ..security.jail import WorkspaceJail
from . import patch as patchlib


class PreviewError(Exception):
    """خطأ يمنع إنشاء معاينة آمنة قبل الموافقة."""


class PatchPreview(BaseModel):
    """لقطة غير قابلة للتغيير لنتيجة patch قبل الكتابة."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    diff: str
    source_hash: str = Field(min_length=64, max_length=64)
    patch_hash: str = Field(min_length=64, max_length=64)
    result_hash: str = Field(min_length=64, max_length=64)
    additions: int = Field(default=0, ge=0)
    removals: int = Field(default=0, ge=0)
    creates_file: bool = False


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_patch_text(patch_text: str) -> str:
    text = patch_text or ""
    if "\\n" in text and "\n" not in text:
        text = text.replace("\\n", "\n")
    return text


def _counts(diff: str) -> tuple[int, int]:
    additions = sum(
        1 for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    removals = sum(
        1 for line in diff.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )
    return additions, removals


class PatchPreviewService:
    """ينفذ نفس تحليل patch داخل الذاكرة دون تعديل القرص."""

    def __init__(self, jail: WorkspaceJail, state: SessionState):
        self.jail = jail
        self.state = state

    def generate(self, relative_path: str, patch_text: str) -> PatchPreview:
        rel = (relative_path or "").removeprefix("./")
        if not rel:
            raise PreviewError("preview requires a relative file path")

        path = self.jail.check(rel)
        patch_text = _normalize_patch_text(patch_text)
        patch_hash = _sha256(patch_text)

        exists = path.exists()
        if exists:
            if rel in self.state.read_files:
                pass
            else:
                raise PreviewError(
                    f"refused: you must read_file({rel}) before patching it"
                )
            try:
                path = self.jail.check_readable(rel)
                old = path.read_text(encoding="utf-8")
            except Exception as exc:
                raise PreviewError(f"preview read failed for {rel}: {exc}") from exc

            expected_hash = self.state.read_hashes.get(rel)
            source_hash = _sha256(old)
            if expected_hash and expected_hash != source_hash:
                raise PreviewError(
                    f"preview refused: {rel} changed after read; re-read the file"
                )
        else:
            self.jail.check_writable_dir(rel)
            old = ""
            source_hash = _sha256(old)

        try:
            blocks = patchlib.parse_blocks(patch_text)
            if exists:
                new = patchlib.apply_blocks(old, blocks)
            else:
                if any(find.strip() for find, _ in blocks):
                    raise PreviewError(
                        "creating a file requires empty SEARCH blocks"
                    )
                new = "\n".join(replace for _, replace in blocks)
        except PreviewError:
            raise
        except patchlib.PatchError as exc:
            raise PreviewError(str(exc)) from exc

        diff = patchlib.make_diff(rel, old, new)
        additions, removals = _counts(diff)
        return PatchPreview(
            path=rel,
            diff=diff,
            source_hash=source_hash,
            patch_hash=patch_hash,
            result_hash=_sha256(new),
            additions=additions,
            removals=removals,
            creates_file=not exists,
        )

    @staticmethod
    def verify_source(preview: PatchPreview, path: Path, current_text: str) -> None:
        current_hash = _sha256(current_text)
        if current_hash != preview.source_hash:
            raise PreviewError(
                f"source changed after preview for {preview.path}; approval invalid"
            )
