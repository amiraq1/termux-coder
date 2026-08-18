from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from . import patch as patchlib
from .edit import _atomic_write, _save_backup, _sha256
from .preview import PatchPlanPreview, PatchPreview, PatchPreviewService, PreviewError


class PatchOperationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    patch: str = Field(min_length=1)
    reason: str = Field(default="", max_length=1000)


class PatchPlanArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: list[PatchOperationArgs] = Field(min_length=1, max_length=32)
    summary: str = Field(default="", max_length=2000)


class RollbackPlanArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=1, max_length=64)


class PatchPlanExecutionError(Exception):
    """Raised internally when a transaction cannot be completed safely."""


def _new_content(old: str, patch_text: str, exists: bool) -> str:
    try:
        blocks = patchlib.parse_blocks(patch_text)
        if exists:
            return patchlib.apply_blocks(old, blocks)
        if any(find.strip() for find, _ in blocks):
            raise PatchPlanExecutionError(
                "creating a file requires empty SEARCH blocks"
            )
        return "\n".join(replace for _, replace in blocks)
    except patchlib.PatchError as exc:
        raise PatchPlanExecutionError(str(exc)) from exc


def _preview_matches(expected: PatchPlanPreview, current: PatchPlanPreview) -> bool:
    return (
        expected.plan_id == current.plan_id
        and expected.source_hash == current.source_hash
        and expected.patch_hash == current.patch_hash
        and expected.result_hash == current.result_hash
    )


def _records_for_plan(ctx: Any, plan_id: str) -> list[dict]:
    return [
        record
        for record in ctx.state.applied_patches
        if isinstance(record, dict) and record.get("plan_id") == plan_id
    ]


def _restore_records(records: list[dict]) -> list[str]:
    errors: list[str] = []
    for record in reversed(records):
        path = Path(record["absolute_path"])
        try:
            if record.get("created"):
                path.unlink(missing_ok=True)
                continue
            backup = Path(record["backup"])
            old_content = backup.read_text(encoding="utf-8")
            _atomic_write(
                path,
                old_content,
                original_mode=record.get("original_mode"),
            )
        except Exception as exc:
            errors.append(f"{record.get('path', path)}: {exc}")
    return errors


async def apply_patch_plan(args: PatchPlanArgs, ctx) -> str:
    """Preview, approve, apply, verify hashes, and rollback as one transaction."""
    preview_service = PatchPreviewService(ctx.jail, ctx.state)
    try:
        current_preview = preview_service.generate_plan(args.operations, args.summary)
    except PreviewError as exc:
        return f"patch plan refused: {exc}"

    approved_preview = getattr(ctx, "orchestrator_plan_preview", None)
    if approved_preview is not None:
        if not isinstance(approved_preview, PatchPlanPreview):
            return "patch plan refused: invalid orchestrator preview"
        if not _preview_matches(approved_preview, current_preview):
            return "patch plan refused: plan changed after preview or approval"
        approved = True
    else:
        approved = await ctx.ui.request_approval(
            "patch_plan",
            {
                "plan_id": current_preview.plan_id,
                "summary": args.summary,
                "diff": current_preview.diff,
                "paths": [preview.path for preview in current_preview.operations],
                "additions": current_preview.additions,
                "removals": current_preview.removals,
            },
        )
    ctx.audit.log(
        "patch_plan_approval",
        plan_id=current_preview.plan_id,
        approved=approved,
        paths=[preview.path for preview in current_preview.operations],
        source_hash=current_preview.source_hash[:16],
        patch_hash=current_preview.patch_hash[:16],
        result_hash=current_preview.result_hash[:16],
    )
    if not approved:
        return "user rejected the patch plan"

    prepared: list[tuple[PatchOperationArgs, PatchPreview, Path, str, str, int | None]] = []
    try:
        for operation, operation_preview in zip(args.operations, current_preview.operations):
            rel = operation.path.removeprefix("./")
            path = ctx.jail.check(rel)
            exists = path.exists()
            if exists:
                path = ctx.jail.check_readable(rel)
                old = path.read_text(encoding="utf-8")
                expected_hash = ctx.state.read_hashes.get(rel)
                if expected_hash and expected_hash != _sha256(old):
                    raise PatchPlanExecutionError(
                        f"{rel} changed after read; re-read the file"
                    )
                original_mode = path.stat().st_mode
            else:
                ctx.jail.check_writable_dir(rel)
                old = ""
                original_mode = None
            new = _new_content(old, operation.patch, exists)
            if _sha256(old) != operation_preview.source_hash:
                raise PatchPlanExecutionError(f"source changed after preview for {rel}")
            if _sha256(new) != operation_preview.result_hash:
                raise PatchPlanExecutionError(f"result changed after preview for {rel}")
            prepared.append(
                (operation, operation_preview, path, old, new, original_mode)
            )
    except (OSError, PatchPlanExecutionError, PreviewError) as exc:
        return f"patch plan refused before write: {exc}"

    records: list[dict] = []
    try:
        for operation, operation_preview, path, old, new, original_mode in prepared:
            backup_path: Path | None = None
            if path.exists():
                backup_path = _save_backup(path, old, ctx.settings.backup_dir)
            record = {
                "plan_id": current_preview.plan_id,
                "path": operation_preview.path,
                "absolute_path": str(path),
                "backup": str(backup_path) if backup_path else None,
                "created": backup_path is None,
                "original_mode": original_mode,
                "old_hash": _sha256(old),
                "new_hash": _sha256(new),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            records.append(record)

        for record, (_, operation_preview, path, old, new, original_mode) in zip(
            records, prepared
        ):
            _atomic_write(path, new, original_mode=original_mode)
            ctx.state.read_files.add(record["path"])
            ctx.state.read_hashes[record["path"]] = record["new_hash"]

    except Exception as exc:
        rollback_errors = _restore_records(records)
        suffix = f"; rollback errors: {rollback_errors}" if rollback_errors else ""
        ctx.audit.log(
            "patch_plan_failed",
            plan_id=current_preview.plan_id,
            error=str(exc),
            rollback_errors=rollback_errors,
        )
        return f"patch plan failed and was rolled back: {exc}{suffix}"

    ctx.state.applied_patches.extend(records)
    setattr(ctx, "last_patch_plan_id", current_preview.plan_id)
    for record, (_, operation_preview, _, _, _, _) in zip(records, prepared):
        ctx.audit.log(
            "patch_plan_file_applied",
            plan_id=current_preview.plan_id,
            path=record["path"],
            old_hash=record["old_hash"][:16],
            new_hash=record["new_hash"][:16],
            backup=record["backup"],
        )
        diff = operation_preview.diff
        additions = operation_preview.additions
        removals = operation_preview.removals
        await ctx.ui.on_event(
            "patch_applied",
            path=record["path"],
            diff=diff,
            additions=additions,
            removals=removals,
            plan_id=current_preview.plan_id,
        )

    ctx.audit.log(
        "patch_plan_applied",
        plan_id=current_preview.plan_id,
        paths=[record["path"] for record in records],
        additions=current_preview.additions,
        removals=current_preview.removals,
    )
    return (
        f"patch plan applied: {current_preview.plan_id} "
        f"({len(records)} files, +{current_preview.additions}/-{current_preview.removals})"
    )


def rollback_plan_internal(ctx: Any, plan_id: str) -> list[str]:
    """Rollback a plan without UI approval; used only after verified failure."""
    records = _records_for_plan(ctx, plan_id)
    if not records:
        return [f"no applied plan found for {plan_id}"]
    errors = _restore_records(records)
    if errors:
        return errors
    for record in records:
        try:
            ctx.state.applied_patches.remove(record)
        except ValueError:
            pass
        if record.get("created"):
            ctx.state.read_files.discard(record["path"])
            ctx.state.read_hashes.pop(record["path"], None)
        else:
            backup = Path(record["backup"])
            ctx.state.read_hashes[record["path"]] = _sha256(
                backup.read_text(encoding="utf-8")
            )
    setattr(ctx, "last_patch_plan_id", None)
    ctx.audit.log(
        "patch_plan_rollback",
        plan_id=plan_id,
        paths=[record["path"] for record in records],
    )
    return []


async def rollback_patch_plan(args: RollbackPlanArgs, ctx) -> str:
    records = _records_for_plan(ctx, args.plan_id)
    if not records:
        return f"rollback plan error: no applied plan found for {args.plan_id}"

    approved = await ctx.ui.request_approval(
        "rollback_plan",
        {"plan_id": args.plan_id, "paths": [record["path"] for record in records]},
    )
    if not approved:
        return "user rejected plan rollback"

    errors = rollback_plan_internal(ctx, args.plan_id)
    if errors:
        return f"rollback plan incomplete for {args.plan_id}: {errors}"
    return f"patch plan rollback applied: {args.plan_id}"
