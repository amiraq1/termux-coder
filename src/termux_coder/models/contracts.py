"""
contracts.py — عقود البيانات الموحَّدة لطبقة Orchestration.

التسلسل الهرمي للمعرفات:
  session_id  : معرف الجلسة المستمرة
  turn_id     : معرف دورة مستخدم واحدة (رسالة → نتيجة)
  call_id     : معرف استدعاء أداة واحد داخل الدورة

لا تُستخدم هذه المعرفات بشكل مترادف.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..tools.preview import PatchPreview


# ══════════════════════════════════════════════════════════════
# 1. كودات الخطأ
# ══════════════════════════════════════════════════════════════

class ErrorCode(str, Enum):
    """كودات الخطأ القياسية — تُرجع كـ `ToolError.code`."""
    UNKNOWN_TOOL        = "unknown_tool"
    INVALID_ARGS        = "invalid_args"
    POLICY_DENY         = "policy_deny"
    APPROVAL_REQUIRED   = "approval_required"
    APPROVAL_EXPIRED    = "approval_expired"
    APPROVAL_MISMATCH   = "approval_mismatch"
    EXECUTION_ERROR     = "execution_error"
    TIMEOUT             = "timeout"
    CANCELLED           = "cancelled"
    WORKSPACE_VIOLATION = "workspace_violation"
    BINARY_FILE         = "binary_file"
    TOCTOU_CONFLICT     = "toctou_conflict"
    BACKUP_FAILED       = "backup_failed"
    PREVIEW_FAILED      = "preview_failed"
    MAX_ROUNDS          = "max_rounds"


# ══════════════════════════════════════════════════════════════
# 2. ToolCall — استدعاء أداة واحد
# ══════════════════════════════════════════════════════════════

class ToolCall(BaseModel):
    """
    يمثل استدعاء أداة واحد صادرًا عن النموذج.

    call_id   : معرف الاستدعاء الفريد (من النموذج أو مولَّد)
    turn_id   : الدورة التي ينتمي إليها هذا الاستدعاء
    name      : اسم الأداة كما يراها النموذج
    arguments : المعاملات الخام كـ dict قبل التحقق
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id:   str = Field(min_length=1)
    turn_id:   str = Field(min_length=1)
    name:      str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)

    @property
    def arguments_fingerprint(self) -> str:
        """
        SHA-256 لمعاملات الاستدعاء — للتحقق أن الموافقة صدرت
        على نفس المعاملات التي عُرضت على المستخدم.
        """
        canonical = json.dumps(self.arguments, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()


# ══════════════════════════════════════════════════════════════
# 3. ToolError — خطأ منظَّم
# ══════════════════════════════════════════════════════════════

class ToolError(BaseModel):
    """خطأ منظَّم يُرفق بـ ToolResult.ok=False."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    code:      ErrorCode
    message:   str = Field(min_length=1)
    retryable: bool = False
    details:   dict[str, Any] = Field(default_factory=dict)


# ══════════════════════════════════════════════════════════════
# 4. ToolResult — نتيجة الأداة (نجاح أو فشل)
# ══════════════════════════════════════════════════════════════

class ToolResult(BaseModel):
    """
    نتيجة موحَّدة لتنفيذ أداة.

    ضمانات:
    - ok=True  => error is None
    - ok=False => error is not None
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    ok:          bool
    tool:        str = Field(min_length=1)
    call_id:     str = Field(min_length=1)
    data:        Any = None
    error:       ToolError | None = None
    duration_ms: int = Field(default=0, ge=0)
    ts_utc:      str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @model_validator(mode="after")
    def _check_consistency(self) -> "ToolResult":
        if self.ok and self.error is not None:
            raise ValueError("ok=True is incompatible with a non-None error")
        if not self.ok and self.error is None:
            raise ValueError("ok=False requires a non-None error")
        return self

    # ── مصانع مختصرة ─────────────────────────────────────────

    @classmethod
    def success(
        cls, tool: str, call_id: str, data: Any = None, duration_ms: int = 0
    ) -> "ToolResult":
        return cls(ok=True, tool=tool, call_id=call_id, data=data, duration_ms=duration_ms)

    @classmethod
    def failure(
        cls,
        tool: str,
        call_id: str,
        code: ErrorCode,
        message: str,
        retryable: bool = False,
        details: dict | None = None,
        duration_ms: int = 0,
    ) -> "ToolResult":
        return cls(
            ok=False,
            tool=tool,
            call_id=call_id,
            error=ToolError(
                code=code,
                message=message,
                retryable=retryable,
                details=details or {},
            ),
            duration_ms=duration_ms,
        )

    def to_content_str(self, max_chars: int = 8000) -> str:
        """
        تحويل النتيجة إلى نص JSON للإرسال كـ tool message.
        يُقيَّد الحجم ويُشار إلى الاقتصاص.
        """
        if self.ok:
            payload: dict[str, Any] = {"ok": True, "tool": self.tool}
            if self.data is not None:
                payload["result"] = self.data
        else:
            payload = {
                "ok": False,
                "tool": self.tool,
                "error": {
                    "code": self.error.code.value,
                    "message": self.error.message,
                    "retryable": self.error.retryable,
                },
            }
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw) > max_chars:
            payload["truncated"] = True
            raw = json.dumps(payload, ensure_ascii=False)[:max_chars] + "…"
        return raw


# ══════════════════════════════════════════════════════════════
# 5. ProviderResponse — استجابة المزود الموحَّدة
# ══════════════════════════════════════════════════════════════

class ProviderResponse(BaseModel):
    """
    استجابة موحَّدة من أي مزود نموذج.

    assistant_message : رسالة المساعد الكاملة (role=assistant)
                        يجب حفظها في تاريخ المحادثة قبل نتائج الأدوات.
    tool_calls        : قائمة ToolCall (فارغة إذا لم يطلب أدوات)
    finish_reason     : سبب الإنهاء (stop, tool_calls, length, ...)
    usage             : إحصائيات tokens إذا أعادها المزود
    """
    model_config = ConfigDict(extra="ignore")

    assistant_message: dict[str, Any]
    tool_calls:        list[ToolCall] = Field(default_factory=list)
    finish_reason:     str | None = None
    usage:             dict[str, int] | None = None
    provider_id:       str | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


# ══════════════════════════════════════════════════════════════
# 6. ApprovalGrant — وثيقة الموافقة
# ══════════════════════════════════════════════════════════════

class ApprovalGrant(BaseModel):
    """
    وثيقة موافقة قصيرة العمر مرتبطة ببصمة الاستدعاء.

    لا تُقبل موافقة إذا:
    - تغيّر arguments_fingerprint بعد عرضها
    - انتهى expires_at
    - لم يطابق call_id الاستدعاء الفعلي
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id:               str
    turn_id:               str
    tool_name:             str
    arguments_fingerprint: str
    approved_by:           str = "user"
    approved_at:           str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    expires_at:            str | None = None  # ISO 8601 UTC
    preview_source_hash:   str | None = None
    preview_patch_hash:    str | None = None
    preview_result_hash:   str | None = None

    def is_valid_for(
        self, call: ToolCall, preview: PatchPreview | None = None
    ) -> tuple[bool, str]:
        """
        تحقق من أن الموافقة صالحة للاستدعاء `call`.
        يُعيد (True, "") أو (False, سبب_الرفض).
        """
        if self.call_id != call.call_id:
            return False, f"call_id mismatch: {self.call_id} != {call.call_id}"
        if self.tool_name != call.name:
            return False, f"tool_name mismatch: {self.tool_name} != {call.name}"
        if self.arguments_fingerprint != call.arguments_fingerprint:
            return False, "arguments changed after approval was granted"
        if self.expires_at:
            now = datetime.now(timezone.utc).isoformat()
            if now > self.expires_at:
                return False, f"approval expired at {self.expires_at}"
        if preview is not None:
            checks = (
                (self.preview_source_hash, preview.source_hash, "source hash"),
                (self.preview_patch_hash, preview.patch_hash, "patch hash"),
                (self.preview_result_hash, preview.result_hash, "result hash"),
            )
            for approved, current, label in checks:
                if approved is not None and approved != current:
                    return False, f"{label} changed after approval"
        return True, ""


# ══════════════════════════════════════════════════════════════
# 7. EvaluatedToolCall — استدعاء بعد تقييم السياسة
# ══════════════════════════════════════════════════════════════

class DecisionKind(str, Enum):
    ALLOW            = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY             = "deny"


class EvaluatedToolCall(BaseModel):
    """
    استدعاء أداة بعد تقييم السياسة.
    يحمل قرار السياسة وبصمة المعاملات للتحقق لاحقًا.
    """
    model_config = ConfigDict(extra="forbid")

    call:           ToolCall
    decision:       DecisionKind
    deny_reason:    str | None = None
    preview_error:  str | None = None
    preview:        PatchPreview | None = None
    approval_grant: ApprovalGrant | None = None

    @property
    def is_ready_to_execute(self) -> bool:
        """هل الاستدعاء جاهز للتنفيذ (مسموح أو موافق عليه)?"""
        if self.decision == DecisionKind.ALLOW:
            return True
        if self.decision == DecisionKind.REQUIRE_APPROVAL and self.approval_grant:
            valid, _ = self.approval_grant.is_valid_for(self.call, self.preview)
            return valid
        return False
