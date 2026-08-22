"""write_file — policy-gated file creation for reports and generated artifacts.

Security contract (in order):
    user intent → path policy → content policy → preview → approval
    → atomic write → verification → audit

The tool NEVER decides path validity itself: every path passes through the
centralized policy in this module, which combines WorkspaceJail resolution,
commonpath containment (never startswith), symlink escape checks, sensitive-
name rejection, and one explicit SD-card report directory allowance.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..security.jail import JailViolation


class WriteFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=2_000_000)
    overwrite: bool = False
    purpose: Literal["report", "generated_artifact"] = "report"


# ── Centralized path policy ─────────────────────────────────────────────

MAX_REPORT_BYTES = 2_000_000  # matches WriteFileArgs.content limit (UTF-8)

SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}
SENSITIVE_SUFFIXES = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".token",
)
PROTECTED_DIRS = {".git", ".termux_coder", "secrets", ".ssh"}


class PathPolicyError(Exception):
    """Raised when a write path violates the centralized write policy."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def sd_report_root() -> Path:
    """The single allowed external (SD card) report directory."""
    return Path.home() / "storage" / "shared" / "termux-coder"


SD_INTENT_PATTERN = re.compile(
    r"\b(sd[\s-]?card|shared storage|external storage|storage/shared|حفظ\s+الخارج|بطاقة\s+الذاكرة)\b"
    r"|~/storage/|/storage/shared/",
    re.IGNORECASE,
)


def has_external_save_intent(user_text: str) -> bool:
    """True only when the user explicitly asked to save outside the workspace."""
    return bool(SD_INTENT_PATTERN.search(user_text or ""))


def resolve_write_target(
    jail,  # WorkspaceJail
    raw_path: str,
    *,
    external_intent: bool,
) -> tuple[Path, bool]:
    """
    Resolve and validate a write target.

    Returns (resolved_path, external). Raises PathPolicyError with a
    classified reason code on any violation. Uses resolve() +
    is_relative_to()/commonpath semantics — never startswith.
    """
    raw = (raw_path or "").strip()
    if not raw:
        raise PathPolicyError("invalid_path", "write_file requires a non-empty path")

    p = Path(raw).expanduser()
    external = False
    if p.is_absolute() or str(p).startswith("~"):
        target_root = sd_report_root()
        try:
            resolved = p.resolve()
        except OSError as exc:
            raise PathPolicyError("invalid_path", f"path cannot be resolved: {exc}") from exc
        root_resolved = target_root.resolve()
        if os.path.commonpath([str(resolved), str(root_resolved)]) != str(root_resolved):
            raise PathPolicyError(
                "outside_jail",
                f"absolute paths are only writable under {target_root}",
            )
        if resolved == root_resolved:
            raise PathPolicyError("invalid_path", "path must name a file, not a directory")
        external = True
        if not external_intent:
            raise PathPolicyError(
                "external_intent_missing",
                "writing outside the workspace requires an explicit save-to-SD-card request",
            )
    else:
        try:
            resolved = jail.check_writable_dir(raw)
        except JailViolation as exc:
            raise PathPolicyError("outside_jail", str(exc)) from exc

    _reject_sensitive(resolved)
    _reject_symlink_escape(resolved)
    return resolved, external


def _reject_sensitive(path: Path) -> None:
    parts = {part.lower() for part in path.parts}
    if parts & PROTECTED_DIRS:
        raise PathPolicyError(
            "sensitive_path",
            f"refusing to write under protected directories: {sorted(parts & PROTECTED_DIRS)}",
        )
    name = path.name.lower()
    if name in SENSITIVE_NAMES or name.endswith(SENSITIVE_SUFFIXES):
        raise PathPolicyError("sensitive_path", f"refusing to write sensitive file: {path.name}")


def _reject_symlink_escape(path: Path) -> None:
    """Reject when the target or any existing parent is a symlink that leaves its tree."""
    probe = path
    while True:
        if probe.is_symlink():
            link_target = probe.resolve()
            if not str(link_target).startswith(str(probe.parent.resolve()) + os.sep) and \
               link_target != probe.parent.resolve():
                raise PathPolicyError(
                    "symlink_escape",
                    f"symlink at {probe} resolves outside its directory",
                )
        parent = probe.parent
        if parent == probe:
            return
        probe = parent


# ── Atomic write ────────────────────────────────────────────────────────

def atomic_write_new(path: Path, content: str) -> dict:
    """
    Atomic create-or-replace: temp file in same dir → flush → fsync → chmod
    0600 → os.replace. Never partial on crash; never copies an existing
    file's permissions.
    """
    encoded = content.encode("utf-8")
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(dir=parent, prefix=".tc_wf_")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return {"bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()}


# ── Handler ─────────────────────────────────────────────────────────────

def _display_path(path: Path, external: bool, jail) -> str:
    if external:
        return str(path)
    try:
        return jail.rel(path)
    except ValueError:
        return str(path)


async def write_file(args: WriteFileArgs, ctx) -> str:
    """Policy-gated file write. Metadata-only audit; never logs content."""
    external_intent = has_external_save_intent(getattr(ctx, "user_text", "") or "")

    # 1. Path policy (centralized; the handler never validates paths itself).
    try:
        path, external = resolve_write_target(
            ctx.jail, args.path, external_intent=external_intent
        )
    except PathPolicyError as exc:
        ctx.audit.log(
            "write_file_denied", reason_code=exc.reason_code, path=str(args.path)
        )
        return f"write refused ({exc.reason_code}): {exc}"

    # 2. Content policy: size bound (UTF-8 bytes, not chars).
    size = len(args.content.encode("utf-8"))
    if size > MAX_REPORT_BYTES:
        ctx.audit.log("write_file_denied", reason_code="content_too_large", path=_display_path(path, external, ctx.jail))
        return f"write refused (content_too_large): {size} bytes exceeds {MAX_REPORT_BYTES}"

    exists = path.exists()
    if exists and not path.is_file():
        return f"write refused (invalid_path): not a regular file: {path}"
    if exists and not args.overwrite:
        ctx.audit.log(
            "write_file_denied",
            reason_code="exists_no_overwrite",
            path=_display_path(path, external, ctx.jail),
        )
        return (
            f"write refused (exists_no_overwrite): {_display_path(path, external, ctx.jail)} "
            "already exists; pass overwrite=true after explicit user approval"
        )

    # 3. Preview → approval → atomic write. When the orchestrator approved
    # (Safe Preview flow), ctx carries the verified write-file preview and we
    # must not re-ask; standalone calls (no preview) ask the UI directly.
    preview = getattr(ctx, "orchestrator_writefile_preview", None)
    approval_granted = getattr(ctx, "orchestrator_approval_granted", False)
    old_hash = None
    if exists:
        old_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if preview is None and not approval_granted:
            approved = await ctx.ui.request_approval(
                "write_file",
                {
                    "title": "Approve overwrite?",
                    "path": _display_path(path, external, ctx.jail),
                    "old_sha256": old_hash,
                    "new_sha256": hashlib.sha256(args.content.encode()).hexdigest(),
                    "bytes": size,
                },
            )
            ctx.audit.log("write_file_approval", path=_display_path(path, external, ctx.jail), approved=approved)
            if not approved:
                return "user rejected the write"
    elif preview is None and not approval_granted:
        # New file: still show what will be created before writing.
        approved = await ctx.ui.request_approval(
            "write_file",
            {
                "title": "Approve new file?",
                "path": _display_path(path, external, ctx.jail),
                "bytes": size,
                "new_sha256": hashlib.sha256(args.content.encode()).hexdigest(),
            },
        )
        ctx.audit.log("write_file_approval", path=_display_path(path, external, ctx.jail), approved=approved)
        if not approved:
            return "user rejected the write"

    # 4. Atomic write.
    try:
        meta = atomic_write_new(path, args.content)
    except Exception as exc:
        ctx.audit.log(
            "write_file_failed",
            path=_display_path(path, external, ctx.jail),
            error=str(exc),
        )
        return f"write error: {exc}"

    # 5. Verification + metadata-only audit.
    written_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if written_hash != meta["sha256"]:
        ctx.audit.log("write_file_verify_failed", path=_display_path(path, external, ctx.jail))
        return "write error: post-write verification failed (hash mismatch)"

    ctx.audit.log(
        "write_file_result",
        path=_display_path(path, external, ctx.jail),
        bytes=meta["bytes"],
        sha256=meta["sha256"],
        created=not exists,
        overwritten=exists,
        purpose=args.purpose,
        external=external,
        ok=True,
    )
    await ctx.ui.on_event(
        "write_file_ok",
        path=_display_path(path, external, ctx.jail),
        bytes=meta["bytes"],
        created=not exists,
    )
    return (
        f"wrote {_display_path(path, external, ctx.jail)} "
        f"({meta['bytes']} bytes, sha256 {meta['sha256'][:16]}…, "
        f"{'created' if not exists else 'overwritten'})"
    )
