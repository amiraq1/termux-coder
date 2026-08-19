from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from . import patch as patchlib
from .symbol import SymbolPatchArgs, SymbolTarget, SymbolResolutionError, build_symbol_patch

class ApplyPatchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    patch: str

class RollbackPatchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str


def _sha256(text: str) -> str:
    """SHA-256 لمحتوى نصي مُرمَّز كـ UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, content: str, original_mode: int | None = None) -> None:
    """
    كتابة ذرية آمنة:
    1. إنشاء ملف مؤقت في نفس المجلد (لضمان نفس نظام الملفات)
    2. كتابة المحتوى مع flush + fsync
    3. ضبط صلاحيات الملف الأصلي إذا كانت متاحة
    4. os.replace: ذري داخل نفس نظام الملفات
    5. مزامنة المجلد للحفاظ على الاتساق
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path_str = tempfile.mkstemp(dir=parent, prefix=".tc_tmp_")
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())

        # الحفاظ على صلاحيات الملف الأصلي
        if original_mode is not None:
            try:
                os.chmod(tmp_path, stat.S_IMODE(original_mode))
            except OSError:
                pass  # Termux قد لا يدعم بعض أوضاع الصلاحيات

        # استبدال ذري
        os.replace(tmp_path_str, str(path))

        # مزامنة المجلد
        try:
            dir_fd = os.open(str(parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass  # بعض أنظمة الملفات لا تدعم fsync على المجلدات

    except Exception:
        # تنظيف الملف المؤقت في حالة الفشل
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _save_backup(path: Path, content: str, backup_dir: Path) -> Path:
    """
    حفظ نسخة احتياطية قبل أي تعديل.
    يعيد مسار ملف النسخة الاحتياطية.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    # استخدام hash أول 8 أحرف لتفادي تصادم الأسماء
    content_hash = _sha256(content)[:8]
    backup_name = f"{path.name}.{stamp}.{content_hash}.bak"
    backup_path = backup_dir / backup_name
    _atomic_write(backup_path, content)
    return backup_path


async def apply_patch(args: ApplyPatchArgs, ctx) -> str:
    rel_input = args.path or ""

    # تطبيع المسار - إزالة ./
    if rel_input.startswith("./"):
        rel_input = rel_input[2:]
    patch_text = args.patch or ""

    # فك هروب \n الحرفية (من Recovery Layer)
    if "\\n" in patch_text and "\n" not in patch_text:
        patch_text = patch_text.replace("\\n", "\n")

    try:
        path = ctx.jail.check(rel_input)
        rel = ctx.jail.rel(path)
    except Exception as exc:
        return f"patch error: {exc}"

    if path.exists():
        # ── ملف موجود: تحقق من القراءة المسبقة ────────────
        if rel not in ctx.state.read_files:
            return f"refused: you must read_file({rel}) before patching it"

        # تحقق من أن الملف ليس مجلداً أو ثنائياً
        if path.is_dir():
            return f"patch error: {rel} is a directory"
        if not path.is_file():
            return f"patch error: {rel} is not a regular file"

        old = path.read_text(encoding="utf-8", errors="replace")

        # ── hash للكشف عن التغيير المتزامن ─────────────────
        expected_hash = ctx.state.read_hashes.get(rel)
        current_hash = _sha256(old)
        if expected_hash and expected_hash != current_hash:
            return (
                f"patch refused: {rel} was modified after you read it "
                f"(expected {expected_hash[:8]}…, got {current_hash[:8]}…). "
                f"Re-read the file before patching."
            )

        try:
            blocks = patchlib.parse_blocks(patch_text)
        except patchlib.PatchError:
            rec = patchlib.recover_simple_patch(patch_text, old)
            if rec is None:
                return "patch error: no SEARCH/REPLACE blocks; re-send with exact markers."
            blocks = [rec]
            await ctx.ui.on_event("patch_recovered", path=rel)

        try:
            new = patchlib.apply_blocks(old, blocks)
        except patchlib.PatchError as exc:
            return f"patch error: {exc}"
    else:
        try:
            blocks = patchlib.parse_blocks(patch_text)
        except patchlib.PatchError:
            return "patch error: creating a file requires SEARCH/REPLACE markers with empty SEARCH."
        if any(find.strip() for find, _ in blocks):
            return "file does not exist; use an empty SEARCH block to create it"
        old = ""
        new = "\n".join(replace for _, replace in blocks)

    # إذا تمت الموافقة عبر Orchestrator، يجب أن تطابق النتيجة المعاينة حرفيًا.
    preview = getattr(ctx, "orchestrator_preview", None)
    if preview is not None:
        if preview.path != rel:
            return "patch refused: preview path mismatch"
        if preview.source_hash != _sha256(old):
            return "patch refused: source changed after preview"
        if preview.patch_hash != _sha256(patch_text):
            return "patch refused: patch changed after preview"
        if preview.result_hash != _sha256(new):
            return "patch refused: result changed after preview"

    diff = patchlib.make_diff(rel, old, new)

    if getattr(ctx, "orchestrator_approval_granted", False):
        approved = True
    else:
        approved = await ctx.ui.request_approval("patch", {"diff": diff, "path": rel})
    ctx.audit.log("patch_approval", path=rel, approved=approved, source="orchestrator" if getattr(ctx, "orchestrator_approval_granted", False) else "tool")
    if not approved:
        return "user rejected the patch"

    # ── حفظ نسخة احتياطية قبل الكتابة ──────────────────────
    backup_path: Path | None = None
    original_mode: int | None = None

    if path.exists():
        try:
            original_mode = path.stat().st_mode
            backup_path = _save_backup(path, old, ctx.settings.backup_dir)
            ctx.audit.log(
                "backup_created",
                path=rel,
                backup=str(backup_path),
                hash=_sha256(old)[:16],
            )
        except Exception as exc:
            return f"patch aborted: could not create backup: {exc}"

    # ── كتابة ذرية ────────────────────────────────────────
    try:
        _atomic_write(path, new, original_mode=original_mode)
    except Exception as exc:
        # حاول الاسترداد إذا فشلت الكتابة وكان لدينا نسخة احتياطية
        ctx.audit.log("patch_write_failed", path=rel, error=str(exc))
        return f"patch error: write failed: {exc}"

    # ── تحديث الحالة ────────────────────────────────────────
    new_hash = _sha256(new)
    ctx.state.read_files.add(rel)
    ctx.state.read_hashes[rel] = new_hash  # تحديث الـ hash للنسخة الجديدة
    ctx.state.applied_patches.append(
        {
            "path": rel,
            "backup": str(backup_path) if backup_path else None,
            "created": backup_path is None,
            "old_hash": _sha256(old) if old else None,
            "new_hash": new_hash,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    )

    ctx.audit.log(
        "patch_applied",
        path=rel,
        old_hash=_sha256(old)[:16] if old else None,
        new_hash=new_hash[:16],
        backup=str(backup_path) if backup_path else None,
    )

    adds = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    rems = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
    await ctx.ui.on_event("patch_applied", path=rel, diff=diff, additions=adds, removals=rems)

    if rel.endswith(".py") and ctx.lsp is not None:
        try:
            await ctx.lsp.notify_change(path, new)
            problems = await ctx.lsp.diagnostics(path)
        except Exception:
            problems = []
        await ctx.ui.on_event(
            "lsp_diag", path=rel, count=len(problems),
            first=problems[0] if problems else "clean",
        )
        if problems:
            return (
                f"patch applied to {rel}\nLSP diagnostics:\n" + "\n".join(problems[:10])
            )

    return f"patch applied to {rel}"


async def apply_symbol_patch(args: SymbolPatchArgs, ctx) -> str:
    """Resolve and patch one Python symbol through the normal safe patch path."""
    rel_input = args.path or ""
    if rel_input.startswith("./"):
        rel_input = rel_input[2:]
    try:
        path = ctx.jail.check_readable(rel_input)
        rel = ctx.jail.rel(path)
    except Exception as exc:
        return f"symbol patch error: {exc}"

    if rel not in ctx.state.read_files:
        return f"refused: you must read_file({rel}) before symbol patching it"

    try:
        source = path.read_text(encoding="utf-8")
        current_hash = _sha256(source)
        expected_hash = ctx.state.read_hashes.get(rel)
        if expected_hash and expected_hash != current_hash:
            return (
                f"symbol patch refused: {rel} was modified after you read it "
                f"(expected {expected_hash[:8]}…, got {current_hash[:8]}…). "
                "Re-read the file before patching."
            )
        target = SymbolTarget(
            path=rel,
            name=args.name,
            kind=args.kind,
            expected_signature=args.expected_signature,
        )
        resolved, patch_text = build_symbol_patch(source, target, args.replacement)
        ctx.audit.log(
            "symbol_resolved",
            path=rel,
            name=resolved.name,
            kind=resolved.kind,
            start_line=resolved.start_line,
            end_line=resolved.end_line,
            source_hash=current_hash[:16],
        )
    except SymbolResolutionError as exc:
        return f"symbol patch error: {exc}"
    except Exception as exc:
        return f"symbol patch error: {exc}"

    return await apply_patch(
        ApplyPatchArgs(path=rel, patch=patch_text),
        ctx,
    )


async def rollback_patch(args: RollbackPatchArgs, ctx) -> str:
    """
    أداة التراجع عن آخر ترقيع.
    تستعيد الملف من النسخة الاحتياطية المحفوظة.
    """
    rel_input = args.path or ""
    if rel_input.startswith("./"):
        rel_input = rel_input[2:]

    try:
        path = ctx.jail.check(rel_input)
        rel = ctx.jail.rel(path)
    except Exception as exc:
        return f"rollback error: {exc}"

    # ابحث عن آخر ترقيع لهذا الملف
    patch_record = None
    for record in reversed(ctx.state.applied_patches):
        if isinstance(record, dict) and record.get("path") == rel:
            patch_record = record
            break

    if patch_record is None:
        return f"rollback error: no patch record found for {rel}"

    created = bool(patch_record.get("created"))
    backup_str = patch_record.get("backup")
    backup_path = Path(backup_str) if backup_str else None
    if not created:
        if backup_path is None:
            return f"rollback error: no backup available for {rel}"
        if not backup_path.exists():
            return f"rollback error: backup file missing: {backup_path}"

    # تأكيد المستخدم
    approved = await ctx.ui.request_approval(
        "rollback",
        {
            "path": rel,
            "backup": str(backup_path) if backup_path else None,
            "created": created,
        },
    )
    if not approved:
        return "user rejected rollback"

    try:
        if created:
            if path.exists():
                if not path.is_file():
                    return f"rollback error: created path is not a regular file: {rel}"
                path.unlink()
            ctx.state.read_files.discard(rel)
            ctx.state.read_hashes.pop(rel, None)
            source = "created_file_removed"
            restored_hash = None
        else:
            old_content = backup_path.read_text(encoding="utf-8")
            original_mode = path.stat().st_mode if path.exists() else None
            _atomic_write(path, old_content, original_mode=original_mode)
            ctx.state.read_hashes[rel] = _sha256(old_content)
            source = "backup_restored"
            restored_hash = _sha256(old_content)[:16]
    except Exception as exc:
        return f"rollback error: {exc}"

    try:
        ctx.state.applied_patches.remove(patch_record)
    except ValueError:
        pass
    ctx.audit.log(
        "rollback_applied",
        path=rel,
        backup=str(backup_path) if backup_path else None,
        created=created,
        source=source,
        hash=restored_hash,
    )

    if created:
        return f"rollback removed created file {rel}"
    return f"rollback applied to {rel} from {backup_path.name}"
