from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from termux_coder.core.agent import ToolContext
from termux_coder.core.context import SessionState
from termux_coder.core.orchestrator import AgentOrchestrator
from termux_coder.core.registry import ToolRegistry
from termux_coder.providers.mock import MockProvider
from termux_coder.security.audit import AuditLog
from termux_coder.security.jail import WorkspaceJail
from termux_coder.security.policy import CommandPolicy, PolicyEngine
from termux_coder.tools import edit, transaction
from termux_coder.tools.preview import PatchPreviewService
from termux_coder.core.verification import VerificationRunner


@dataclass
class E2ESettings:
    security_mode: str = "ASK"
    max_output_chars: int = 8000
    max_file_chars: int = 30000
    command_timeout: int = 10
    backup_dir: Path | None = None


class E2EUI:
    def __init__(self, approve: bool = True, before_approval=None):
        self.approve = approve
        self.before_approval = before_approval
        self.events: list[tuple[str, dict]] = []

    def thinking(self):
        from contextlib import nullcontext
        return nullcontext()

    async def on_token(self, _text: str) -> None:
        pass

    async def on_event(self, kind: str, **payload) -> None:
        self.events.append((kind, payload))

    async def request_approval(self, kind: str, payload: dict) -> bool:
        if self.before_approval is not None:
            self.before_approval(kind, payload)
        return self.approve


@pytest.fixture
def e2e_workspace(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text(
        'def greet(name):\n    return "Hello, " + name\n',
        encoding="utf-8",
    )
    return project


@pytest.fixture
def e2e_components(e2e_workspace: Path):
    jail = WorkspaceJail(e2e_workspace)
    settings = E2ESettings(backup_dir=e2e_workspace / ".termux_coder" / "backups")
    state = SessionState()
    main = (e2e_workspace / "main.py").read_text(encoding="utf-8")
    import hashlib
    state.read_files.add("main.py")
    state.read_hashes["main.py"] = hashlib.sha256(main.encode()).hexdigest()
    audit = AuditLog(e2e_workspace / ".termux_coder" / "audit.jsonl")
    ui = E2EUI()
    policy = CommandPolicy("ASK")
    policy_engine = PolicyEngine("ASK")
    ctx = ToolContext(
        jail=jail,
        settings=settings,
        state=state,
        ui=ui,
        audit=audit,
        policy=policy,
        policy_engine=policy_engine,
        repomap=None,
        lsp=None,
    )
    registry = ToolRegistry()
    registry.register("apply_patch", "Apply a patch", edit.ApplyPatchArgs, edit.apply_patch)
    registry.register("rollback_patch", "Rollback a patch", edit.RollbackPatchArgs, edit.rollback_patch)
    registry.register("apply_patch_plan", "Apply a multi-file patch plan", transaction.PatchPlanArgs, transaction.apply_patch_plan)
    registry.register("rollback_patch_plan", "Rollback a patch plan", transaction.RollbackPlanArgs, transaction.rollback_patch_plan)
    return {
        "workspace": e2e_workspace,
        "jail": jail,
        "settings": settings,
        "state": state,
        "audit": audit,
        "ui": ui,
        "ctx": ctx,
        "registry": registry,
        "provider": MockProvider([]),
        "policy_engine": policy_engine,
    }


def build_orchestrator(components, responses, *, ui=None):
    ui = ui or components["ui"]
    provider = MockProvider(responses)
    return AgentOrchestrator(
        provider=provider,
        registry=components["registry"],
        policy_engine=components["policy_engine"],
        audit=components["audit"],
        ctx=components["ctx"],
        max_rounds=5,
        max_duration_s=10,
        on_event=ui.on_event,
        approval_handler=ui.request_approval,
        preview_service=PatchPreviewService(components["jail"], components["state"]),
        verification_runner=VerificationRunner(components["workspace"], components["settings"]),
    )
