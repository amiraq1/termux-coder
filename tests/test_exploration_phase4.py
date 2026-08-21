import pytest
from termux_coder.core.exploration import ExplorationTask, ExplorationManager, ExplorationTaskSpec
from termux_coder.core.orchestrator import AgentOrchestrator
from termux_coder.security.policy import PolicyEngine, Permission
from termux_coder.models.contracts import ToolCall, DecisionKind

def test_exploration_task_status_transitions():
    task = ExplorationTask(turn_id="turn_1", task_id="dissect:turn_1:core", title="Core", scope="core")

    assert task.status == "pending"
    task.start()
    assert task.status == "running"

    task.finish("failed", error="some error")
    assert task.status == "failed"

    # Cannot transition from failed to completed
    with pytest.raises(ValueError, match="Cannot transition from failed to completed"):
        task.finish("completed")

def test_dissection_mode_rejects_mutation_before_preview():
    # Mocking components
    class MockProvider:
        pass
    class MockRegistry:
        pass
    class MockAudit:
        def log(self, *args, **kwargs):
            pass
    class MockContext:
        pass
    class MockPreview:
        def generate(self, *args, **kwargs):
            raise Exception("Should not reach generate()")

    policy_engine = PolicyEngine(mode="ASK")
    # By default apply_patch has write permission

    orchestrator = AgentOrchestrator(
        provider=MockProvider(),
        registry=MockRegistry(),
        policy_engine=policy_engine,
        audit=MockAudit(),
        ctx=MockContext(),
        preview_service=MockPreview(),
        dissection_mode=True
    )

    # Try apply_patch
    call = ToolCall(call_id="call_1", turn_id="turn_1", name="apply_patch", arguments={"path": "foo", "patch": "bar"})
    evaluated = orchestrator._evaluate_call(call)

    assert evaluated.decision == DecisionKind.DENY
    assert "dissection_mode" in evaluated.deny_reason
    assert "mutation permission" in evaluated.deny_reason
    assert evaluated.preview is None

def test_dissection_mode_allows_read_tools():
    class MockProvider:
        pass
    class MockRegistry:
        pass
    class MockAudit:
        def log(self, *args, **kwargs):
            pass
    class MockContext:
        pass

    policy_engine = PolicyEngine(mode="ASK")

    orchestrator = AgentOrchestrator(
        provider=MockProvider(),
        registry=MockRegistry(),
        policy_engine=policy_engine,
        audit=MockAudit(),
        ctx=MockContext(),
        dissection_mode=True
    )

    # read_file should be allowed to require approval or just allowed depending on mode
    call = ToolCall(call_id="call_2", turn_id="turn_1", name="read_file", arguments={"path": "foo"})
    evaluated = orchestrator._evaluate_call(call)

    # Since it's ASK mode and read_file is READ permission, it might be allowed directly or require approval
    # In PolicyEngine ASK mode, READ requires approval if not AUTO. Wait, read_ok is low risk, allows True, False
    # Check what policy engine returns:
    assert evaluated.decision in {DecisionKind.ALLOW, DecisionKind.REQUIRE_APPROVAL}


@pytest.mark.anyio
async def test_exploration_manager_summary_with_failure():
    from termux_coder.core.exploration import ExplorationManager, ExplorationTaskSpec, ExplorationEvent

    manager = ExplorationManager(turn_id="turn_123")
    specs = [
        ExplorationTaskSpec(task_id="dissect:turn_123:core", title="Core", scope="core"),
        ExplorationTaskSpec(task_id="dissect:turn_123:tools", title="Tools", scope="tools")
    ]

    async def worker(task):
        if "tools" in task.scope:
            raise TimeoutError("timeout after execution limit")
        return "success"

    await manager.run(specs, worker)

    summary = manager.get_summary()
    assert "Coverage: 1/2 completed" in summary
    assert "FAILED: tools" in summary
    assert "timeout" in summary
    assert "partial dissection; not full repository understanding" in summary

def test_agent_orchestrator_receives_dissection_mode():
    from termux_coder.core.orchestrator import AgentOrchestrator
    from termux_coder.security.policy import PolicyEngine

    class MockProvider: pass
    class MockRegistry: pass
    class MockAudit: pass
    class MockContext: pass

    # Prove that it can be instantiated and the attribute is set
    orchestrator = AgentOrchestrator(
        provider=MockProvider(),
        registry=MockRegistry(),
        policy_engine=PolicyEngine(),
        audit=MockAudit(),
        ctx=MockContext(),
        dissection_mode=True
    )

    assert orchestrator.dissection_mode is True


@pytest.mark.anyio
async def test_dissection_mode_full_turn_denies_mutation_before_preview():
    """Full turn → _evaluate_call: a mutation call is DENY'd before any preview."""
    from termux_coder.providers.mock import MockProvider, MockResponse
    from termux_coder.core.orchestrator import TurnState
    from termux_coder.models.contracts import ErrorCode

    mutation_called: list[object] = []
    preview_calls: list[str] = []

    class RecordingAudit:
        def __init__(self) -> None:
            self.events: list[dict] = []

        def log(self, event: str, **data) -> None:
            self.events.append({"event": event, **data})

        def has(self, event: str) -> bool:
            return any(e["event"] == event for e in self.events)

    class MockRegistry:
        def __init__(self, tools: dict) -> None:
            self._tools = tools

        def handler(self, name: str):
            return self._tools.get(name)

        def schemas(self):
            return [{"function": {"name": n}} for n in self._tools]

    async def fake_apply_patch(args, ctx):
        mutation_called.append(True)
        return "patched"

    class CountingPreview:
        def generate(self, *a, **k):
            preview_calls.append("generate")
            return None

        def generate_symbol(self, *a, **k):
            preview_calls.append("symbol")

        def generate_plan(self, *a, **k):
            preview_calls.append("plan")

    class MockContext:
        pass

    audit = RecordingAudit()
    provider = MockProvider([
        MockResponse.with_tool("c1", "apply_patch", {"path": "x.py", "patch": "..."}),
        MockResponse.text("I cannot patch in dissection mode."),
    ])
    registry = MockRegistry({"apply_patch": fake_apply_patch})

    orchestrator = AgentOrchestrator(
        provider=provider,
        registry=registry,
        policy_engine=PolicyEngine(mode="ASK"),
        audit=audit,
        ctx=MockContext(),
        preview_service=CountingPreview(),
        dissection_mode=True,
        max_rounds=5,
        max_duration_s=30.0,
    )

    msgs = [{"role": "user", "content": "analyze the repository structure"}]
    result = await orchestrator.run_turn(msgs)

    # 1. The mutation handler was never executed — denied before execution.
    assert mutation_called == []
    # 2. No preview was generated — denied BEFORE preview.
    assert preview_calls == []
    # 3. The audit trail recorded the denial.
    assert audit.has("tool_denied")
    # 4. The tool result carries a policy-deny error code.
    assert any(r.error and r.error.code == ErrorCode.POLICY_DENY for r in result.tool_results)
    # 5. The turn still terminates cleanly (denial feeds back to the model).
    assert result.state == TurnState.IDLE


def test_dissection_mode_setting_respects_env(monkeypatch):
    from termux_coder.config import Settings

    # Default: off (no env).
    monkeypatch.delenv("TERMUX_CODER_DISSECT", raising=False)
    monkeypatch.delenv("DISSECT", raising=False)
    assert Settings().dissection_mode is False

    # Env var enables it.
    monkeypatch.setenv("TERMUX_CODER_DISSECT", "1")
    assert Settings().dissection_mode is True

    # Explicit off still respects False.
    monkeypatch.setenv("TERMUX_CODER_DISSECT", "0")
    assert Settings().dissection_mode is False
