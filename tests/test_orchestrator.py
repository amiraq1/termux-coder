"""
test_orchestrator.py — اختبارات آلة حالات AgentOrchestrator.

يغطي:
- المسارات الصحيحة: allow, deny, approval, cancel, max_rounds
- الاتساق بين العقود
- سلامة الموافقة وبصمة المعاملات
"""
from __future__ import annotations

import asyncio
import pytest

from termux_coder.core.orchestrator import (
    AgentOrchestrator,
    StateTransitionError,
    TurnState,
)
from termux_coder.core.registry import ToolRegistry
from termux_coder.models.contracts import (
    DecisionKind,
    ErrorCode,
    ToolCall,
    ToolResult,
)
from termux_coder.providers.mock import MockProvider, MockResponse
from termux_coder.security.audit import AuditLog
from termux_coder.security.policy import PolicyEngine


# ── مساعدات الاختبار ──────────────────────────────────────

class FakeAudit:
    """سجل تدقيق وهمي يجمع الأحداث."""
    def __init__(self):
        self.events: list[dict] = []

    def log(self, event: str, **data) -> None:
        self.events.append({"event": event, **data})

    def tail(self, n: int = 50) -> list[dict]:
        return self.events[-n:]

    def has(self, event: str) -> bool:
        return any(e["event"] == event for e in self.events)


class FakeCtx:
    """سياق وهمي يحمل الإعدادات."""
    class FakeSettings:
        max_output_chars = 8000

    settings = FakeSettings()


def build_registry(tools: dict | None = None) -> ToolRegistry:
    from pydantic import BaseModel, ConfigDict
    
    class FakeArgs(BaseModel):
        model_config = ConfigDict(extra="allow")

    reg = ToolRegistry()
    for name, handler in (tools or {}).items():
        reg.register(
            name,
            f"{name} tool",
            FakeArgs,
            handler,
        )
    return reg


def build_orchestrator(
    responses: list[MockResponse],
    mode: str = "AUTO",
    tools: dict | None = None,
    max_rounds: int = 5,
) -> tuple[AgentOrchestrator, FakeAudit, MockProvider]:
    """بناء orchestrator جاهز للاختبار."""
    audit    = FakeAudit()
    provider = MockProvider(responses)
    reg      = build_registry(tools)
    policy   = PolicyEngine(mode)
    orch = AgentOrchestrator(
        provider=provider,
        registry=reg,
        policy_engine=policy,
        audit=audit,
        ctx=FakeCtx(),
        max_rounds=max_rounds,
        max_duration_s=30.0,
    )
    return orch, audit, provider


MSGS = [{"role": "user", "content": "hello"}]


# ── اختبارات العقود ─────────────────────────────────────────

class TestToolResultContract:
    """اختبارات عقد ToolResult."""

    def test_success_has_no_error(self):
        r = ToolResult.success("read_file", "c1", data="content")
        assert r.ok is True
        assert r.error is None
        assert r.data == "content"

    def test_failure_has_error(self):
        r = ToolResult.failure(
            "apply_patch", "c1",
            code=ErrorCode.POLICY_DENY,
            message="denied",
        )
        assert r.ok is False
        assert r.error is not None
        assert r.error.code == ErrorCode.POLICY_DENY

    def test_ok_true_with_error_raises(self):
        from termux_coder.models.contracts import ToolError
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ToolResult(
                ok=True,
                tool="t",
                call_id="c",
                error=ToolError(code=ErrorCode.TIMEOUT, message="x"),
            )

    def test_ok_false_without_error_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ToolResult(ok=False, tool="t", call_id="c")

    def test_to_content_str_success(self):
        r = ToolResult.success("read_file", "c1", data="hello")
        content = r.to_content_str()
        import json
        parsed = json.loads(content)
        assert parsed["ok"] is True
        assert parsed["result"] == "hello"

    def test_to_content_str_failure(self):
        r = ToolResult.failure(
            "run_command", "c1",
            code=ErrorCode.POLICY_DENY,
            message="blocked",
        )
        content = r.to_content_str()
        import json
        parsed = json.loads(content)
        assert parsed["ok"] is False
        assert parsed["error"]["code"] == "policy_deny"


# ── اختبارات ToolCall ───────────────────────────────────────

class TestToolCall:
    def test_fingerprint_deterministic(self):
        c1 = ToolCall(call_id="x", turn_id="t", name="read_file", arguments={"path": "a.py"})
        c2 = ToolCall(call_id="x", turn_id="t", name="read_file", arguments={"path": "a.py"})
        assert c1.arguments_fingerprint == c2.arguments_fingerprint

    def test_fingerprint_changes_with_args(self):
        c1 = ToolCall(call_id="x", turn_id="t", name="read_file", arguments={"path": "a.py"})
        c2 = ToolCall(call_id="x", turn_id="t", name="read_file", arguments={"path": "b.py"})
        assert c1.arguments_fingerprint != c2.arguments_fingerprint


# ── اختبارات ApprovalGrant ───────────────────────────────────

class TestApprovalGrant:
    def _make_call(self, path="a.py"):
        return ToolCall(
            call_id="call-1",
            turn_id="turn-1",
            name="apply_patch",
            arguments={"path": path, "patch": "..."},
        )

    def test_valid_grant_accepted(self):
        from termux_coder.models.contracts import ApprovalGrant
        call = self._make_call()
        grant = ApprovalGrant(
            call_id="call-1",
            turn_id="turn-1",
            tool_name="apply_patch",
            arguments_fingerprint=call.arguments_fingerprint,
        )
        valid, reason = grant.is_valid_for(call)
        assert valid, reason

    def test_wrong_call_id_rejected(self):
        from termux_coder.models.contracts import ApprovalGrant
        call = self._make_call()
        grant = ApprovalGrant(
            call_id="call-999",
            turn_id="turn-1",
            tool_name="apply_patch",
            arguments_fingerprint=call.arguments_fingerprint,
        )
        valid, reason = grant.is_valid_for(call)
        assert not valid
        assert "call_id" in reason

    def test_changed_arguments_rejected(self):
        from termux_coder.models.contracts import ApprovalGrant
        call_original = self._make_call("a.py")
        call_modified = self._make_call("evil.py")
        grant = ApprovalGrant(
            call_id="call-1",
            turn_id="turn-1",
            tool_name="apply_patch",
            arguments_fingerprint=call_original.arguments_fingerprint,
        )
        valid, reason = grant.is_valid_for(call_modified)
        assert not valid
        assert "arguments changed" in reason

    def test_expired_grant_rejected(self):
        from termux_coder.models.contracts import ApprovalGrant
        call = self._make_call()
        grant = ApprovalGrant(
            call_id="call-1",
            turn_id="turn-1",
            tool_name="apply_patch",
            arguments_fingerprint=call.arguments_fingerprint,
            expires_at="2000-01-01T00:00:00+00:00",  # ماضي
        )
        valid, reason = grant.is_valid_for(call)
        assert not valid
        assert "expired" in reason


# ── اختبارات آلة الحالات ─────────────────────────────────

class TestStateMachineTransitions:
    """يختبر آلة الحالات مباشرة."""

    def test_invalid_transition_raises(self):
        """لا يمكن الانتقال من IDLE إلى EXECUTING مباشرة."""
        orch, _, _ = build_orchestrator([])
        from termux_coder.core.orchestrator import TurnState, StateTransitionError
        with pytest.raises(StateTransitionError):
            orch._transition(TurnState.EXECUTING)

    def test_idle_to_planning_allowed(self):
        orch, _, _ = build_orchestrator([])
        orch._transition(TurnState.PLANNING)
        assert orch.state == TurnState.PLANNING

    def test_planning_to_cancelled_allowed(self):
        orch, _, _ = build_orchestrator([])
        orch._transition(TurnState.PLANNING)
        orch._transition(TurnState.CANCELLED)
        assert orch.state == TurnState.CANCELLED


# ── سيناريوهات الدورة ───────────────────────────────────────

class TestTurnScenarios:

    def test_text_only_response(self):
        """استجابة نصية — لا أدوات."""
        async def _run():
            orch, audit, _ = build_orchestrator([
                MockResponse.text("Hello, world!"),
            ])
            msgs = list(MSGS)
            result = await orch.run_turn(msgs)

            assert result.state == TurnState.IDLE
            assert result.final_text == "Hello, world!"
            assert result.rounds_used == 1
            assert len(result.tool_results) == 0
            # رسالة المساعد أضيفت للتاريخ
            assert any(m["role"] == "assistant" for m in msgs)
        asyncio.run(_run())

    def test_single_allowed_tool(self):
        """أداة واحدة بدون موافقة (AUTO + READ)."""
        async def _run():
            called = []

            async def fake_read(args, ctx):
                called.append(args.model_dump())
                return "file content"

            orch, audit, _ = build_orchestrator(
                responses=[
                    MockResponse.with_tool("c1", "read_file", {"path": "x.py"}),
                    MockResponse.text("Done reading."),
                ],
                mode="AUTO",
                tools={"read_file": fake_read},
            )
            msgs = list(MSGS)
            result = await orch.run_turn(msgs)

            assert result.state == TurnState.IDLE
            assert len(called) == 1
            assert called[0] == {"path": "x.py"}
            assert len(result.tool_results) == 1
            assert result.tool_results[0].ok is True

            # التسلسل الصحيح في التاريخ: user -> assistant(tool_call) -> tool -> assistant
            roles = [m["role"] for m in msgs]
            assert roles == ["user", "assistant", "tool", "assistant"]
        asyncio.run(_run())

    def test_deny_does_not_execute(self):
        """أداة مرفوضة بـ DENY لا تُنفذ ولا تطلب موافقة."""
        async def _run():
            called = []

            async def fake_write(args, ctx):
                called.append(args.model_dump())
                return "written"

            # READONLY لا يسمح بالكتابة
            orch, audit, _ = build_orchestrator(
                responses=[
                    MockResponse.with_tool("c1", "apply_patch", {"path": "x.py", "patch": "..."}),
                    MockResponse.text("I cannot patch in READONLY mode."),
                ],
                mode="READONLY",
                tools={"apply_patch": fake_write},
            )
            msgs = list(MSGS)
            result = await orch.run_turn(msgs)

            # الأداة لم تُنفذ
            assert len(called) == 0
            # التدقيق يسجل الرفض
            assert audit.has("tool_denied")
            # النتيجة خطأ بـ POLICY_DENY
            assert any(r.error and r.error.code == ErrorCode.POLICY_DENY for r in result.tool_results)
        asyncio.run(_run())

    def test_deny_is_not_converted_to_approval(self):
        """DENY لا يتحول إلى REQUIRE_APPROVAL تلقائياً."""
        async def _run():
            orch, _, _ = build_orchestrator(
                responses=[MockResponse.with_tool("c1", "apply_patch", {"path": "x.py", "patch": "..."})],
                mode="READONLY",
                tools={"apply_patch": lambda a, c: "never"},
            )
            call = ToolCall(
                call_id="c1", turn_id="t1",
                name="apply_patch",
                arguments={"path": "x.py", "patch": "..."},
            )
            ecall = orch._evaluate_call(call)
            # يجب أن يكون DENY وليس REQUIRE_APPROVAL
            assert ecall.decision == DecisionKind.DENY
        asyncio.run(_run())

    def test_max_rounds_reached(self):
        """يتوقف عند max_rounds ويُعيد FAILED."""
        async def _run():
            counter = [0]

            async def loop_tool(args, ctx):
                counter[0] += 1
                return "still running"

            # الأداة تُطلب في كل جولة، لكن الحد هو 3
            orch, audit, _ = build_orchestrator(
                responses=[
                    MockResponse.with_tool(f"c{i}", "read_file", {})
                    for i in range(10)
                ],
                mode="AUTO",
                tools={"read_file": loop_tool},
                max_rounds=3,
            )
            msgs = list(MSGS)
            result = await orch.run_turn(msgs)

            assert result.state == TurnState.FAILED
            assert result.rounds_used == 3
            assert "max_rounds" in (result.error or "")
            assert audit.has("max_rounds_reached")
        asyncio.run(_run())

    def test_cancel_during_turn(self):
        """الإلغاء أثناء الدورة ينتهي بـ CANCELLED بأمان."""
        async def _run():
            cancel_called = []

            async def slow_tool(args, ctx):
                await asyncio.sleep(1)  # لن يكتمل
                return "done"

            orch, audit, provider = build_orchestrator(
                responses=[MockResponse.with_tool("c1", "read_file", {})],
                mode="AUTO",
                tools={"read_file": slow_tool},
            )

            msgs = list(MSGS)
            task = asyncio.create_task(orch.run_turn(msgs))
            
            # let it start and hit the slow_tool
            for _ in range(50):
                if orch.state == TurnState.EXECUTING:
                    break
                await asyncio.sleep(0.01)

            # ألغِ أثناء التنفيذ
            await orch.cancel_turn()
            result = await task

            # النتيجة يجب أن تعكس الإلغاء
            assert result.state in (TurnState.CANCELLED, TurnState.FAILED)
        asyncio.run(_run())

    def test_unknown_tool_returns_error(self):
        """أداة غير مسجلة تعطي UNKNOWN_TOOL دون استثناء."""
        async def _run():
            orch, _, _ = build_orchestrator(
                responses=[
                    MockResponse.with_tool("c1", "hack_the_planet", {}),
                    MockResponse.text("Sorry."),
                ],
                mode="AUTO",
                tools={},  # لا أدوات مسجلة
            )
            msgs = list(MSGS)
            result = await orch.run_turn(msgs)

            # النتيجة تحتوي خطأ UNKNOWN_TOOL أو POLICY_DENY (غير معروفة في policy)
            assert len(result.tool_results) == 1
            tool_res = result.tool_results[0]
            assert not tool_res.ok
            assert tool_res.error.code in (
                ErrorCode.UNKNOWN_TOOL, ErrorCode.POLICY_DENY
            )
        asyncio.run(_run())

    def test_multiple_tools_in_one_response(self):
        """عدة أدوات في استجابة واحدة — كل واحدة تُنفذ ضمن سياسة مستقلة."""
        async def _run():
            called = []

            async def reader(args, ctx):
                d = args.model_dump()
                called.append(d.get("path"))
                return f"content of {d.get('path')}"

            orch, _, _ = build_orchestrator(
                responses=[
                    MockResponse.with_tools([
                        ("c1", "read_file", {"path": "a.py"}),
                        ("c2", "read_file", {"path": "b.py"}),
                    ]),
                    MockResponse.text("Both read."),
                ],
                mode="AUTO",
                tools={"read_file": reader},
            )
            msgs = list(MSGS)
            result = await orch.run_turn(msgs)

            assert result.state == TurnState.IDLE
            assert len(called) == 2
            assert set(called) == {"a.py", "b.py"}
        asyncio.run(_run())

    def test_assistant_message_saved_before_tool_results(self):
        """رسالة المساعد تُحفظ قبل نتائج الأدوات (API contract)."""
        async def _run():
            async def reader(args, ctx):
                return "content"

            orch, _, _ = build_orchestrator(
                responses=[
                    MockResponse.with_tool("c1", "read_file", {"path": "x.py"}),
                    MockResponse.text("OK."),
                ],
                mode="AUTO",
                tools={"read_file": reader},
            )
            msgs = list(MSGS)
            await orch.run_turn(msgs)

            # يجب أن يكون الترتيب: user -> assistant -> tool -> assistant
            roles = [m["role"] for m in msgs]
            assert roles == ["user", "assistant", "tool", "assistant"]

            # رسالة المساعد الأولى يجب أن تحتوي tool_calls
            assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
            assert "tool_calls" in assistant_msgs[0]  # الأولى تحمل الاستدعاءات
        asyncio.run(_run())

    def test_tool_execution_error_returns_failure(self):
        """أداة ترمي استثناءًا تعطي EXECUTION_ERROR."""
        async def _run():
            async def broken_tool(args, ctx):
                raise RuntimeError("disk full")

            orch, _, _ = build_orchestrator(
                responses=[
                    MockResponse.with_tool("c1", "read_file", {"path": "x.py"}),
                    MockResponse.text("Hmm, error."),
                ],
                mode="AUTO",
                tools={"read_file": broken_tool},
            )
            msgs = list(MSGS)
            result = await orch.run_turn(msgs)

            assert len(result.tool_results) == 1
            tr = result.tool_results[0]
            assert not tr.ok
            assert tr.error.code == ErrorCode.EXECUTION_ERROR
            assert "disk full" in tr.error.message
        asyncio.run(_run())


# ── اختبارات الموافقة ─────────────────────────────────────────

class TestApprovalFlow:

    def test_grant_approval_validates_fingerprint(self):
        """الموافقة على call_id غير موجود ترفض."""
        async def _run():
            orch, _, _ = build_orchestrator(
                responses=[MockResponse.text("hi")],
                mode="ASK",
                tools={},
            )
            ok, reason = orch.grant_approval("nonexistent-call")
            assert not ok
            assert "no pending approval" in reason
        asyncio.run(_run())

    def test_approval_flow_with_ask_mode(self):
        """في ASK — الأداة تحتاج موافقة، تُمنح من خارج."""
        async def _run():
            called = []

            async def writer(args, ctx):
                called.append("write")
                return "patch applied"

            orch, audit, _ = build_orchestrator(
                responses=[
                    MockResponse.with_tool("c1", "apply_patch", {"path": "x.py", "patch": "..."}),
                    MockResponse.text("Patched."),
                ],
                mode="ASK",
                tools={"apply_patch": writer},
            )

            msgs = list(MSGS)
            # نشغّل الدورة في الخلفية
            task = asyncio.create_task(orch.run_turn(msgs))

            # انتظر حتى تدخل AWAITING_APPROVAL
            for _ in range(200):
                if orch.state == TurnState.AWAITING_APPROVAL:
                    break
                await asyncio.sleep(0.01)

            assert orch.state == TurnState.AWAITING_APPROVAL, f"state={orch.state}"

            # منح الموافقة
            ok, reason = orch.grant_approval("c1")
            assert ok, reason

            result = await task

            assert result.state == TurnState.IDLE
            assert "write" in called
            assert audit.has("approval_granted")
            assert audit.has("tool_executing")
        asyncio.run(_run())

    def test_approval_with_changed_args_rejected(self):
        """إذا تغيّرت المعاملات بعد الموافقة — التنفيذ يُرفض."""
        async def _run():
            from termux_coder.models.contracts import ApprovalGrant
            call = ToolCall(
                call_id="c1", turn_id="t1",
                name="apply_patch",
                arguments={"path": "a.py", "patch": "..."},
            )
            # إنشاء موافقة بصمة مختلفة (معاملات مختلفة)
            wrong_call = ToolCall(
                call_id="c1", turn_id="t1",
                name="apply_patch",
                arguments={"path": "evil.py", "patch": "..."},
            )
            grant = ApprovalGrant(
                call_id="c1", turn_id="t1",
                tool_name="apply_patch",
                arguments_fingerprint=wrong_call.arguments_fingerprint,
            )
            valid, reason = grant.is_valid_for(call)
            assert not valid
            assert "arguments changed" in reason
        asyncio.run(_run())


# ── اختبارات MockProvider ──────────────────────────────────────

class TestMockProvider:
    def test_text_response(self):
        async def _run():
            provider = MockProvider([MockResponse.text("hello")])
            result = await provider.chat_stream([], [], lambda t: None)
            assert result["content"] == "hello"
            assert "tool_calls" not in result or not result.get("tool_calls")
        asyncio.run(_run())

    def test_tool_call_response(self):
        async def _run():
            provider = MockProvider([
                MockResponse.with_tool("c1", "read_file", {"path": "x.py"}),
            ])
            result = await provider.chat_stream([], [], lambda t: None)
            assert result["tool_calls"]
            tc = result["tool_calls"][0]
            assert tc["function"]["name"] == "read_file"
            assert tc["id"] == "c1"
        asyncio.run(_run())

    def test_exhausted_returns_empty(self):
        async def _run():
            provider = MockProvider([])
            result = await provider.chat_stream([], [], lambda t: None)
            assert result["content"] == ""
        asyncio.run(_run())

    def test_records_calls(self):
        async def _run():
            provider = MockProvider([
                MockResponse.text("a"),
                MockResponse.text("b"),
            ])
            async def noop(t): pass
            await provider.chat_stream([{"role": "user"}], [], noop)
            await provider.chat_stream([], [{"type": "function"}], noop)
            assert len(provider.calls) == 2
            assert provider.calls[0]["messages_count"] == 1
            assert provider.calls[1]["tools_count"] == 1
        asyncio.run(_run())
