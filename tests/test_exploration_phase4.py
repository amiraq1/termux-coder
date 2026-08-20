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

