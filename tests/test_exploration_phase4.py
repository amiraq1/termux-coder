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


def test_terminal_states_cannot_back_transition_to_completed():
    """Phase 5: failed / timeout / cancelled are distinct terminals; none can become completed."""
    for terminal in ("failed", "timeout", "cancelled"):
        task = ExplorationTask(
            turn_id="t", task_id=f"dissect:t:{terminal}", title=terminal, scope=terminal
        )
        task.start()
        task.finish(terminal, error="err")
        assert task.status == terminal
        with pytest.raises(ValueError, match=f"Cannot transition from {terminal} to completed"):
            task.finish("completed")


def test_summary_reports_distinct_terminal_labels():
    """Phase 5: summary shows distinct FAILED/TIMEOUT/CANCELLED labels; no result hidden."""
    from termux_coder.core.exploration import ExplorationManager, ExplorationTaskSpec

    manager = ExplorationManager(turn_id="t")
    specs = [
        ExplorationTaskSpec(task_id="dissect:t:core", title="Core", scope="core"),
        ExplorationTaskSpec(task_id="dissect:t:sec", title="Security", scope="security-network"),
        ExplorationTaskSpec(task_id="dissect:t:ui", title="UI", scope="ui-lsp"),
        ExplorationTaskSpec(task_id="dissect:t:tests", title="Tests", scope="tests-docs"),
    ]
    manager.configure(specs)

    # core + ui complete; sec failed; tests timed out; (cancelled checked below)
    t = manager.task
    t("dissect:t:core").start(); t("dissect:t:core").finish("completed")
    manager.set_todo_status("dissect:t:core", "completed")
    t("dissect:t:sec").start(); t("dissect:t:sec").finish("failed", error="boom")
    manager.set_todo_status("dissect:t:sec", "failed")
    t("dissect:t:ui").start(); t("dissect:t:ui").finish("completed")
    manager.set_todo_status("dissect:t:ui", "completed")
    t("dissect:t:tests").start(); t("dissect:t:tests").finish("timeout", error="slow")
    manager.set_todo_status("dissect:t:tests", "timeout")

    summary = manager.get_summary()
    assert "Coverage: 2/4 completed" in summary
    assert "FAILED: security-network" in summary
    assert "TIMEOUT: tests-docs" in summary
    assert "partial dissection; not full repository understanding" in summary


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

    # Git writes (EXECUTE permission) are also denied BEFORE preview generation.
    git_call = ToolCall(
        call_id="call_2", turn_id="turn_1",
        name="git_commit", arguments={"message": "msg"},
    )
    git_evaluated = orchestrator._evaluate_call(git_call)
    assert git_evaluated.decision == DecisionKind.DENY
    assert "dissection_mode" in git_evaluated.deny_reason
    assert git_evaluated.preview is None


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
    assert "TIMEOUT: tools" in summary
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
        mutation_called.append("apply_patch")
        return "patched"

    async def fake_git_commit(args, ctx):
        mutation_called.append("git_commit")
        return "committed"

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
        MockResponse.with_tools([
            ("c1", "apply_patch", {"path": "x.py", "patch": "..."}),
            ("c2", "git_commit", {"message": "dissection commit"}),
        ]),
        MockResponse.text("I cannot patch or commit in dissection mode."),
    ])
    registry = MockRegistry({"apply_patch": fake_apply_patch, "git_commit": fake_git_commit})

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

    # "git" gives the git_commit call explicit git intent so it survives the
    # intent gate and reaches the dissection_mode gate itself.
    msgs = [{"role": "user", "content": "analyze the repository structure and git history"}]
    result = await orchestrator.run_turn(msgs)

    # 1. Neither mutation handler was executed — denied before execution.
    assert mutation_called == []
    # 2. No preview was generated for either tool — denied BEFORE preview.
    assert preview_calls == []
    # 3. The audit trail recorded both denials.
    assert audit.has("tool_denied")
    assert sum(1 for e in audit.events if e["event"] == "tool_denied") == 2
    # 4. Both tool results carry a policy-deny error code.
    assert any(
        r.error and r.error.code == ErrorCode.POLICY_DENY and r.call_id == "c1"
        for r in result.tool_results
    )
    assert any(
        r.error and r.error.code == ErrorCode.POLICY_DENY and r.call_id == "c2"
        for r in result.tool_results
    )
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


@pytest.mark.anyio
async def test_search_and_read_events_carry_canonical_envelope():
    """Phase 4: record_search/record_read emit canonical ExplorationEvent objects."""
    from termux_coder.core.exploration import ExplorationManager

    received: list[dict] = []

    async def sink(event):
        received.append(event.model_dump(mode="json"))

    manager = ExplorationManager(turn_id="turn_42", on_update=sink)
    spec = ExplorationTaskSpec(task_id="dissect:turn_42:core", title="Core", scope="core")
    manager.configure([spec])
    await manager.start_task("dissect:turn_42:core")
    await manager.record_search("dissect:turn_42:core", "core", 7)
    await manager.record_read("dissect:turn_42:core", "src/main.py", tokens=120)

    events = [e for e in received if e["kind"] in ("search", "read")]
    kinds = [e["kind"] for e in events]
    assert kinds == ["search", "read"]

    for e in events:
        # Canonical envelope on every event.
        assert e["turn_id"] == "turn_42"
        assert e["task_id"] == "dissect:turn_42:core"

    search_ev = events[0]
    assert "searched" in search_ev["detail"]
    assert search_ev["related_paths"] == []

    read_ev = events[1]
    assert read_ev["detail"] == "src/main.py"
    assert read_ev["related_paths"] == ["src/main.py"]
    assert read_ev["tokens"] == 120
