"""
orchestrator.py — AgentOrchestrator: آلة حالات صريحة لدورة الوكيل.

دورة الحياة:
  IDLE -> PLANNING -> AWAITING_APPROVAL -> EXECUTING -> VERIFYING -> IDLE
                   -> CANCELLED
                   -> FAILED

الفصل الأساسي:
  - start_turn()   : يُرسل رسالة المستخدم ويبدأ التخطيط/التنفيذ
  - grant_approval(): يمنح موافقة مرتبطة ببصمة الاستدعاء
  - cancel_turn()  : يُلغي الدورة الحالية بأمان
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, AsyncIterator, Callable, Coroutine

from ..models.contracts import (
    ApprovalGrant,
    DecisionKind,
    ErrorCode,
    EvaluatedToolCall,
    ProviderResponse,
    ToolCall,
    ToolResult,
)
from ..security.audit import AuditLog
from ..security.policy import PolicyEngine
from .registry import ToolRegistry
from .recovery import recover_tool_calls
from ..tools.preview import PatchPreviewService, PreviewError


# ══════════════════════════════════════════════════════════════
# حالات آلة الحالات
# ══════════════════════════════════════════════════════════════

class TurnState(str, Enum):
    IDLE              = "idle"
    PLANNING          = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING         = "executing"
    VERIFYING         = "verifying"
    CANCELLED         = "cancelled"
    FAILED            = "failed"


# الانتقالات المسموحة فقط
_ALLOWED_TRANSITIONS: dict[TurnState, set[TurnState]] = {
    TurnState.IDLE:              {TurnState.PLANNING},
    TurnState.PLANNING:          {TurnState.PLANNING, TurnState.AWAITING_APPROVAL, TurnState.EXECUTING,
                                  TurnState.IDLE, TurnState.CANCELLED, TurnState.FAILED},
    TurnState.AWAITING_APPROVAL: {TurnState.EXECUTING, TurnState.CANCELLED, TurnState.FAILED},
    TurnState.EXECUTING:         {TurnState.EXECUTING, TurnState.PLANNING, TurnState.VERIFYING,
                                  TurnState.IDLE, TurnState.CANCELLED, TurnState.FAILED},
    TurnState.VERIFYING:         {TurnState.PLANNING, TurnState.IDLE,
                                  TurnState.CANCELLED, TurnState.FAILED},
    TurnState.CANCELLED:         {TurnState.IDLE},
    TurnState.FAILED:            {TurnState.IDLE},
}


class StateTransitionError(Exception):
    """رفع عند محاولة انتقال غير مسموح في آلة الحالات."""


# ══════════════════════════════════════════════════════════════
# نتيجة الدورة
# ══════════════════════════════════════════════════════════════

class TurnResult:
    """نتيجة دورة كاملة."""
    __slots__ = ("state", "final_text", "tool_results", "error", "rounds_used")

    def __init__(
        self,
        state: TurnState,
        final_text: str = "",
        tool_results: list[ToolResult] | None = None,
        error: str | None = None,
        rounds_used: int = 0,
    ):
        self.state        = state
        self.final_text   = final_text
        self.tool_results = tool_results or []
        self.error        = error
        self.rounds_used  = rounds_used


# ══════════════════════════════════════════════════════════════
# AgentOrchestrator
# ══════════════════════════════════════════════════════════════

class AgentOrchestrator:
    """
    منسّق الوكيل — آلة حالات صريحة.

    المبادئ الأساسية:
    1. كل انتقال حالة مُسجَّل وقابل للتتبع.
    2. DENY نهائي: لا يتحول إلى طلب موافقة.
    3. الموافقة مقيَّدة ببصمة المعاملات: أي تغيير يُبطلها.
    4. رسالة المساعد تُحفظ في التاريخ قبل نتائج الأدوات.
    5. الأدوات blocking تُنفَّذ في thread pool.
    6. حدود صارمة: max_rounds, max_duration_s.
    """

    def __init__(
        self,
        provider,             # أي مزود يدعم chat_stream(messages, tools, on_token)
        registry: ToolRegistry,
        policy_engine: PolicyEngine,
        audit: AuditLog,
        ctx: Any,             # ToolContext
        *,
        max_rounds: int = 20,
        max_duration_s: float = 300.0,
        on_event: Callable[..., Coroutine] | None = None,
        approval_handler: Callable[[str, dict], Coroutine] | None = None,
        message_sink: Callable[[dict], None] | None = None,
        message_preparer: Callable[[list[dict]], list[dict]] | None = None,
        preview_service: PatchPreviewService | None = None,
    ):
        self.provider       = provider
        self.registry       = registry
        self.policy_engine  = policy_engine
        self.audit          = audit
        self.ctx            = ctx
        self.max_rounds     = max_rounds
        self.max_duration_s = max_duration_s
        self._on_event      = on_event or _noop_event
        self._approval_handler = approval_handler
        self._message_sink = message_sink
        self._message_preparer = message_preparer
        self._preview_service = preview_service

        self._state: TurnState = TurnState.IDLE
        self._turn_id: str | None = None
        self._history: list[dict] = []
        self._pending_approvals: dict[str, EvaluatedToolCall] = {}
        self._cancel_event = asyncio.Event()
        self._tool_results: list[ToolResult] = []

    # ── واجهة الحالة ─────────────────────────────────────────

    @property
    def state(self) -> TurnState:
        return self._state

    def _transition(self, new_state: TurnState) -> None:
        allowed = _ALLOWED_TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            raise StateTransitionError(
                f"Invalid transition {self._state} -> {new_state}. "
                f"Allowed: {', '.join(s.value for s in allowed)}"
            )
        old = self._state
        self._state = new_state
        self.audit.log(
            "state_transition",
            turn_id=self._turn_id,
            from_state=old.value,
            to_state=new_state.value,
        )

    def _append_message(self, messages: list[dict], message: dict) -> None:
        """أضف رسالة إلى تاريخ الدورة واحفظها فورًا عند توفر sink."""
        messages.append(message)
        if self._message_sink is not None:
            self._message_sink(message)

    # ── تقييم السياسة ────────────────────────────────────────

    def _evaluate_call(self, call: ToolCall) -> EvaluatedToolCall:
        """
        تقييم استدعاء أداة ضد السياسة.
        الصلاحية تأتي من TOOL_PERMISSIONS، لا من النموذج.
        """
        decision_raw = self.policy_engine.evaluate_tool(call.name)

        if not decision_raw.allowed:
            # DENY نهائي — لا يتحول إلى REQUIRE_APPROVAL
            kind = DecisionKind.DENY
            deny_reason = decision_raw.reason
            preview = None
            preview_error = None
        elif decision_raw.requires_approval:
            kind = DecisionKind.REQUIRE_APPROVAL
            deny_reason = None
            preview = None
            preview_error = None
            if call.name == "apply_patch" and self._preview_service is not None:
                try:
                    preview = self._preview_service.generate(
                        str(call.arguments.get("path", "")),
                        str(call.arguments.get("patch", "")),
                    )
                except PreviewError as exc:
                    preview_error = str(exc)
                    kind = DecisionKind.DENY
                    deny_reason = preview_error
                if preview is not None:
                    self.audit.log(
                        "patch_preview",
                        turn_id=self._turn_id,
                        call_id=call.call_id,
                        path=preview.path,
                        source_hash=preview.source_hash[:16],
                        patch_hash=preview.patch_hash[:16],
                        result_hash=preview.result_hash[:16],
                        additions=preview.additions,
                        removals=preview.removals,
                    )
        else:
            kind = DecisionKind.ALLOW
            deny_reason = None
            preview = None
            preview_error = None

        return EvaluatedToolCall(
            call=call,
            decision=kind,
            deny_reason=deny_reason,
            preview_error=preview_error,
            preview=preview,
        )

    # ── منح الموافقة ─────────────────────────────────────────

    def grant_approval(
        self,
        call_id: str,
        approved_by: str = "user",
        expires_in_s: float | None = 60.0,
    ) -> tuple[bool, str]:
        """
        منح موافقة على استدعاء معلَّق.

        يُعيد (True, "") إذا نجح، أو (False, سبب) إذا فشل.
        الموافقة مرتبطة ببصمة المعاملات — أي تغيير لاحق يُبطلها.
        """
        ecall = self._pending_approvals.get(call_id)
        if ecall is None:
            return False, f"no pending approval for call_id={call_id!r}"

        if ecall.decision != DecisionKind.REQUIRE_APPROVAL:
            return False, f"call {call_id!r} decision is {ecall.decision.value}, not require_approval"

        expires_at = None
        if expires_in_s is not None:
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in_s)
            ).isoformat()

        grant = ApprovalGrant(
            call_id=call_id,
            turn_id=ecall.call.turn_id,
            tool_name=ecall.call.name,
            arguments_fingerprint=ecall.call.arguments_fingerprint,
            approved_by=approved_by,
            expires_at=expires_at,
            preview_source_hash=ecall.preview.source_hash if ecall.preview else None,
            preview_patch_hash=ecall.preview.patch_hash if ecall.preview else None,
            preview_result_hash=ecall.preview.result_hash if ecall.preview else None,
        )

        # تحقق نهائي من الصلاحية
        valid, reason = grant.is_valid_for(ecall.call, ecall.preview)
        if not valid:
            return False, reason

        # تحديث الاستدعاء المعلَّق بالموافقة
        self._pending_approvals[call_id] = EvaluatedToolCall(
            call=ecall.call,
            decision=ecall.decision,
            preview_error=ecall.preview_error,
            preview=ecall.preview,
            approval_grant=grant,
        )

        self.audit.log(
            "approval_granted",
            turn_id=self._turn_id,
            call_id=call_id,
            tool=ecall.call.name,
            approved_by=approved_by,
            fingerprint=grant.arguments_fingerprint[:16],
        )
        return True, ""

    # ── إلغاء الدورة ─────────────────────────────────────────

    async def cancel_turn(self) -> None:
        """إلغاء الدورة الحالية بأمان."""
        self._cancel_event.set()
        if self._state not in (TurnState.IDLE, TurnState.CANCELLED, TurnState.FAILED):
            try:
                self._transition(TurnState.CANCELLED)
            except StateTransitionError:
                pass
        self.audit.log("turn_cancelled", turn_id=self._turn_id)

    def _is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    # ── بناء ToolCall من مخرجات النموذج الخام ────────────────

    def _parse_raw_calls(
        self, raw_calls: list[dict], turn_id: str
    ) -> list[ToolCall]:
        """
        تحويل tool_calls الخام من النموذج إلى ToolCall objects.
        يُسقط الاستدعاءات ذات المعاملات غير الصالحة.
        """
        result = []
        for raw in raw_calls:
            fn = raw.get("function", {})
            name = fn.get("name", "")
            call_id = raw.get("id") or f"gen-{uuid.uuid4().hex[:12]}"
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                if not isinstance(args, dict):
                    args = {}
            except (json.JSONDecodeError, ValueError):
                args = {}
                self.audit.log(
                    "tool_args_parse_error",
                    call_id=call_id,
                    tool=name,
                    raw=raw_args[:200],
                )
            if name:
                result.append(ToolCall(
                    call_id=call_id,
                    turn_id=turn_id,
                    name=name,
                    arguments=args,
                ))
        return result

    # ── تنفيذ أداة واحدة ─────────────────────────────────────

    async def _execute_one(self, ecall: EvaluatedToolCall) -> ToolResult:
        """
        تنفيذ أداة واحدة بعد التحقق من جاهزيتها.
        الأدوات blocking تُنفَّذ في asyncio.to_thread.
        """
        call = ecall.call
        start = time.monotonic()

        # DENY نهائي ويجب فحصه قبل حالة الجاهزية.
        if ecall.decision == DecisionKind.DENY:
            return ToolResult.failure(
                tool=call.name, call_id=call.call_id,
                code=ErrorCode.POLICY_DENY,
                message=ecall.deny_reason or "denied by policy",
                retryable=False,
            )

        # الاستدعاء غير الموافق عليه لا يُنفذ.
        if not ecall.is_ready_to_execute:
            return ToolResult.failure(
                tool=call.name, call_id=call.call_id,
                code=ErrorCode.APPROVAL_REQUIRED,
                message=ecall.deny_reason or "approval required",
            )

        # التحقق من وجود الأداة
        handler = self.registry.handler(call.name)
        if handler is None:
            return ToolResult.failure(
                tool=call.name, call_id=call.call_id,
                code=ErrorCode.UNKNOWN_TOOL,
                message=f"tool '{call.name}' not found in registry",
            )

        # تحقق من الموافقة إذا كانت مطلوبة
        if ecall.decision == DecisionKind.REQUIRE_APPROVAL:
            if ecall.approval_grant is None:
                return ToolResult.failure(
                    tool=call.name, call_id=call.call_id,
                    code=ErrorCode.APPROVAL_REQUIRED,
                    message="approval required but not granted",
                )
            valid, reason = ecall.approval_grant.is_valid_for(call, ecall.preview)
            if not valid:
                return ToolResult.failure(
                    tool=call.name, call_id=call.call_id,
                    code=ErrorCode.APPROVAL_MISMATCH,
                    message=reason,
                    retryable=False,
                )

        # سجّل قبل التنفيذ
        self.audit.log(
            "tool_executing",
            turn_id=self._turn_id,
            call_id=call.call_id,
            tool=call.name,
            fingerprint=call.arguments_fingerprint[:16],
        )

        # تنفيذ الأداة. يمنع هذا العلم طلب موافقة ثانية داخل الأداة
        # بعد أن تحقق Orchestrator من الموافقة الخارجية.
        previous_approval = getattr(self.ctx, "orchestrator_approval_granted", False)
        previous_preview = getattr(self.ctx, "orchestrator_preview", None)
        setattr(self.ctx, "orchestrator_approval_granted", ecall.is_ready_to_execute)
        setattr(self.ctx, "orchestrator_preview", ecall.preview)
        try:
            raw = await handler(dict(call.arguments), self.ctx)
            duration_ms = int((time.monotonic() - start) * 1000)
            result = ToolResult.success(
                tool=call.name, call_id=call.call_id,
                data=raw, duration_ms=duration_ms,
            )
        except asyncio.CancelledError:
            duration_ms = int((time.monotonic() - start) * 1000)
            result = ToolResult.failure(
                tool=call.name, call_id=call.call_id,
                code=ErrorCode.CANCELLED,
                message="tool execution cancelled",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            result = ToolResult.failure(
                tool=call.name, call_id=call.call_id,
                code=ErrorCode.EXECUTION_ERROR,
                message=str(exc),
                retryable=True,
                duration_ms=duration_ms,
            )
        finally:
            setattr(self.ctx, "orchestrator_approval_granted", previous_approval)
            setattr(self.ctx, "orchestrator_preview", previous_preview)

        self.audit.log(
            "tool_result",
            turn_id=self._turn_id,
            call_id=call.call_id,
            tool=call.name,
            ok=result.ok,
            duration_ms=result.duration_ms,
        )
        return result

    # ── الدورة الرئيسية ──────────────────────────────────────

    async def run_turn(
        self,
        messages: list[dict],
        on_token: Callable | None = None,
    ) -> TurnResult:
        """
        تنفيذ دورة كاملة: PLANNING -> EXECUTING -> (VERIFYING) -> IDLE.

        messages : تاريخ المحادثة الكامل (يُعدَّل في المكان)
        on_token : callback لبث الرموز إلى الواجهة

        ضمانات:
        - رسالة المساعد تُحفظ قبل نتائج الأدوات
        - DENY لا يتحول إلى REQUIRE_APPROVAL
        - الإلغاء يُنهي الحلقة بأمان
        - الحد الأقصى للجولات مُطبَّق صارمًا
        """
        if self._state != TurnState.IDLE:
            return TurnResult(
                state=self._state,
                error=f"orchestrator not idle (current={self._state.value})",
            )

        self._turn_id = uuid.uuid4().hex[:12]
        self._cancel_event.clear()
        self._pending_approvals.clear()
        self._tool_results.clear()
        deadline = time.monotonic() + self.max_duration_s
        on_token = on_token or _noop_token

        self.audit.log("turn_start", turn_id=self._turn_id)
        self._transition(TurnState.PLANNING)
        await self._on_event("turn_start", turn_id=self._turn_id)

        final_text = ""
        rounds_used = 0

        try:
            for round_idx in range(self.max_rounds):
                rounds_used = round_idx + 1

                # ── فحص الإلغاء والمهلة ───────────────────────
                if self._is_cancelled():
                    self._transition(TurnState.CANCELLED)
                    return TurnResult(
                        state=TurnState.CANCELLED,
                        tool_results=self._tool_results,
                        rounds_used=rounds_used,
                    )
                if time.monotonic() > deadline:
                    self._transition(TurnState.FAILED)
                    return TurnResult(
                        state=TurnState.FAILED,
                        error=f"turn exceeded {self.max_duration_s}s limit",
                        tool_results=self._tool_results,
                        rounds_used=rounds_used,
                    )

                # ── استدعاء المزود ────────────────────────────
                self._transition(TurnState.PLANNING)
                await self._on_event("round_start", round=round_idx)

                schemas = self.registry.schemas()
                model_messages = (
                    self._message_preparer(messages)
                    if self._message_preparer is not None
                    else messages
                )
                response = await self.provider.chat_stream(
                    model_messages, schemas, on_token
                )

                # تحويل الاستجابة الخام إلى ProviderResponse
                provider_resp = self._adapt_response(response, self._turn_id)

                # ── حفظ رسالة المساعد أولاً (ضروري للـ API) ──
                self._append_message(messages, provider_resp.assistant_message)
                await self._on_event("assistant_done")

                if not provider_resp.has_tool_calls:
                    # لا أدوات — الدورة انتهت
                    final_text = provider_resp.assistant_message.get("content") or ""
                    self._transition(TurnState.IDLE)
                    self.audit.log(
                        "turn_complete",
                        turn_id=self._turn_id,
                        rounds=rounds_used,
                    )
                    return TurnResult(
                        state=TurnState.IDLE,
                        final_text=final_text,
                        tool_results=self._tool_results,
                        rounds_used=rounds_used,
                    )

                # ── تقييم السياسة لكل استدعاء ────────────────
                evaluated = [self._evaluate_call(c) for c in provider_resp.tool_calls]

                # الاستدعاءات المرفوضة (DENY) — نهائية، لا تعرض للموافقة
                denied = [e for e in evaluated if e.decision == DecisionKind.DENY]
                for ecall in denied:
                    self.audit.log(
                        "tool_denied",
                        turn_id=self._turn_id,
                        call_id=ecall.call.call_id,
                        tool=ecall.call.name,
                        reason=ecall.deny_reason,
                    )
                    await self._on_event(
                        "tool_denied",
                        tool=ecall.call.name,
                        reason=ecall.deny_reason,
                    )
                    # أضف نتيجة DENY إلى التاريخ كـ tool message
                    deny_result = ToolResult.failure(
                        tool=ecall.call.name,
                        call_id=ecall.call.call_id,
                        code=(ErrorCode.PREVIEW_FAILED if ecall.preview_error else ErrorCode.POLICY_DENY),
                        message=ecall.deny_reason or "denied",
                    )
                    self._append_message(messages, {
                        "role": "tool",
                        "tool_call_id": ecall.call.call_id,
                        "content": deny_result.to_content_str(),
                    })
                    self._tool_results.append(deny_result)

                # الاستدعاءات التي تحتاج موافقة
                needs_approval = [
                    e for e in evaluated
                    if e.decision == DecisionKind.REQUIRE_APPROVAL
                ]
                if needs_approval:
                    self._transition(TurnState.AWAITING_APPROVAL)
                    for ecall in needs_approval:
                        self._pending_approvals[ecall.call.call_id] = ecall
                    await self._on_event(
                        "approval_requested",
                        calls=[{
                            "call_id": e.call.call_id,
                            "tool": e.call.name,
                            "arguments": e.call.arguments,
                            "fingerprint": e.call.arguments_fingerprint[:16],
                        } for e in needs_approval],
                    )
                    # اطلب موافقة الواجهة إن كان المسار التفاعلي موصولًا.
                    if self._approval_handler is not None:
                        for ecall in needs_approval:
                            approved = await self._approval_handler(
                                self._approval_kind(ecall.call.name),
                                self._approval_payload(ecall),
                            )
                            if approved:
                                self.grant_approval(ecall.call.call_id)
                            else:
                                self._cancel_event.set()
                                break

                    # انتظر حتى تُمنح جميع الموافقات أو يُلغى
                    granted = await self._wait_for_approvals(needs_approval, deadline)
                    if not granted:
                        self._transition(TurnState.CANCELLED)
                        return TurnResult(
                            state=TurnState.CANCELLED,
                            tool_results=self._tool_results,
                            rounds_used=rounds_used,
                        )
                    self._transition(TurnState.EXECUTING)

                # الاستدعاءات المسموحة مباشرة أو التي تمت الموافقة عليها
                ready = [
                    self._pending_approvals.get(e.call.call_id, e)
                    for e in evaluated
                    if self._pending_approvals.get(e.call.call_id, e).is_ready_to_execute
                ]

                if not ready and denied:
                    # كل الاستدعاءات مرفوضة — أعد للمخطط
                    continue

                # ── تنفيذ الاستدعاءات الجاهزة ────────────────
                self._transition(TurnState.EXECUTING)
                for ecall in ready:
                    if self._is_cancelled():
                        break
                    await self._on_event(
                        "tool_start",
                        tool=ecall.call.name,
                        call_id=ecall.call.call_id,
                    )
                    result = await self._execute_one(ecall)
                    self._tool_results.append(result)

                    content = result.to_content_str(
                        max_chars=getattr(
                            getattr(self.ctx, "settings", None), "max_output_chars", 8000
                        )
                    )
                    self._append_message(messages, {
                        "role": "tool",
                        "tool_call_id": ecall.call.call_id,
                        "content": content,
                    })
                    await self._on_event(
                        "tool_result",
                        tool=ecall.call.name,
                        ok=result.ok,
                        duration_ms=result.duration_ms,
                    )

            # ── تجاوز الحد الأقصى للجولات ────────────────────
            self._transition(TurnState.FAILED)
            self.audit.log(
                "max_rounds_reached",
                turn_id=self._turn_id,
                rounds=rounds_used,
            )
            return TurnResult(
                state=TurnState.FAILED,
                error=f"max_rounds={self.max_rounds} reached",
                tool_results=self._tool_results,
                rounds_used=rounds_used,
            )

        except asyncio.CancelledError:
            self._transition(TurnState.CANCELLED)
            self.audit.log("turn_cancelled_exc", turn_id=self._turn_id)
            return TurnResult(
                state=TurnState.CANCELLED,
                tool_results=self._tool_results,
                rounds_used=rounds_used,
            )
        except Exception as exc:
            try:
                self._transition(TurnState.FAILED)
            except StateTransitionError:
                pass
            self.audit.log(
                "turn_failed",
                turn_id=self._turn_id,
                error=str(exc),
            )
            return TurnResult(
                state=TurnState.FAILED,
                error=str(exc),
                tool_results=self._tool_results,
                rounds_used=rounds_used,
            )
        finally:
            self._pending_approvals.clear()

    # ── انتظار الموافقات ─────────────────────────────────────

    @staticmethod
    def _approval_kind(tool_name: str) -> str:
        if tool_name in {"apply_patch", "rollback_patch"}:
            return "patch"
        if tool_name.startswith("git_"):
            return "git"
        return "command"

    @staticmethod
    def _approval_payload(ecall: EvaluatedToolCall) -> dict:
        call = ecall.call
        args = call.arguments
        if call.name == "apply_patch":
            if ecall.preview is not None:
                return {
                    "path": ecall.preview.path,
                    "diff": ecall.preview.diff,
                    "additions": ecall.preview.additions,
                    "removals": ecall.preview.removals,
                }
            return {"path": args.get("path", ""), "diff": args.get("patch", "")}
        if call.name == "rollback_patch":
            return {"path": args.get("path", ""), "diff": "rollback requested"}
        if call.name.startswith("git_"):
            return {"title": f"Approve {call.name}?", "body": json.dumps(args, ensure_ascii=False)}
        return {"command": args.get("command", json.dumps(args, ensure_ascii=False))}

    async def _wait_for_approvals(
        self,
        calls: list[EvaluatedToolCall],
        deadline: float,
    ) -> bool:
        """
        انتظر حتى تُمنح جميع الموافقات أو يُلغى أو تنتهي المهلة.
        يُعيد True إذا مُنحت جميع الموافقات، False إذا أُلغي.

        ملاحظة: في CLI/TUI الموافقة تُمنح عبر grant_approval().
        هنا نتحقق بشكل دوري حتى يمكن اختبار آلة الحالات.
        """
        while True:
            if self._is_cancelled():
                return False
            if time.monotonic() > deadline:
                return False
            all_granted = all(
                self._pending_approvals.get(e.call.call_id, e).is_ready_to_execute
                for e in calls
            )
            if all_granted:
                # تحديث evaluated calls بالموافقات
                for i, ecall in enumerate(calls):
                    updated = self._pending_approvals.get(ecall.call.call_id)
                    if updated:
                        calls[i] = updated
                return True
            await asyncio.sleep(0.05)

    # ── تكييف استجابة المزود ────────────────────────────────

    def _adapt_response(
        self,
        raw_response: dict | ProviderResponse,
        turn_id: str,
    ) -> ProviderResponse:
        """
        تحويل استجابة المزود الخام إلى ProviderResponse موحَّد.
        يدعم المزودين الذين يعيدون dict أو ProviderResponse مباشرة.
        """
        if isinstance(raw_response, ProviderResponse):
            return raw_response

        # المزودون الحاليون يعيدون dict مباشرة
        assistant_msg = dict(raw_response)
        raw_calls = assistant_msg.pop("tool_calls", None) or []

        # توافق مع المزودات التي تطبع استدعاء الأداة كنص بدل native tool calls.
        if not raw_calls:
            recovered = recover_tool_calls(
                assistant_msg.get("content") or "", self.registry
            )
            raw_calls = recovered or []

        tool_calls = self._parse_raw_calls(raw_calls, turn_id)

        # أعد tool_calls للرسالة الأصلية (ضروري لبعض المزودين)
        if raw_calls:
            assistant_msg["tool_calls"] = raw_calls

        return ProviderResponse(
            assistant_message=assistant_msg,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
        )


# ══════════════════════════════════════════════════════════════
# مساعدات
# ══════════════════════════════════════════════════════════════

async def _noop_event(event: str, **kwargs) -> None:
    pass

async def _noop_token(token: str) -> None:
    pass
