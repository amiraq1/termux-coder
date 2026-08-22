"""Mandatory tests for the policy-gated write_file tool.

Covers: registration, schema, workspace write, traversal, symlink escape,
sensitive paths, overwrite safety, atomicity, permissions, preview-before-
approval, dissection denial, metadata-only audit, and SD-card gating.

The key security test uses a spy on the atomic writer to prove write_file is
never invoked when policy fails or approval is missing.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from termux_coder.core.registry import ToolRegistry
from termux_coder.security.jail import WorkspaceJail
from termux_coder.tools import writefile
from termux_coder.tools.writefile import (
    MAX_REPORT_BYTES,
    PathPolicyError,
    WriteFileArgs,
    atomic_write_new,
    has_external_save_intent,
    resolve_write_target,
    write_file,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@dataclass
class FakeState:
    read_files: set = field(default_factory=set)
    read_hashes: dict = field(default_factory=dict)
    applied_patches: list = field(default_factory=list)


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def log(self, event: str, **data) -> None:
        self.events.append({"event": event, **data})

    def has(self, event: str) -> bool:
        return any(e["event"] == event for e in self.events)


class FakeUI:
    def __init__(self, approved: bool = True) -> None:
        self.approved = approved
        self.requests: list[tuple] = []

    async def request_approval(self, kind: str, payload: dict) -> bool:
        self.requests.append((kind, payload))
        return self.approved

    async def on_event(self, kind: str, **payload) -> None:
        pass


@pytest.fixture()
def jail(tmp_path: Path) -> WorkspaceJail:
    return WorkspaceJail(tmp_path)


def make_ctx(jail: WorkspaceJail, audit: FakeAudit, ui: FakeUI, **extra) -> SimpleNamespace:
    return SimpleNamespace(
        jail=jail,
        settings=SimpleNamespace(backup_dir=jail.root / ".termux_coder" / "backups"),
        state=FakeState(),
        ui=ui,
        audit=audit,
        user_text="save the report",
        **extra,
    )


# ── 1. Registration ─────────────────────────────────────────────────────


def test_write_file_registered_once_in_central_registry():
    from termux_coder.cli import build_registry

    reg = build_registry()
    schemas = [s["function"]["name"] for s in reg.schemas()]
    assert schemas.count("write_file") == 1
    assert reg.handler("write_file") is not None


# ── 2. Schema ───────────────────────────────────────────────────────────


def test_schema_rejects_missing_path_and_oversized_content():
    with pytest.raises(ValidationError):
        WriteFileArgs(content="x")  # path required
    with pytest.raises(ValidationError):
        WriteFileArgs(path="a.md", content="x" * (MAX_REPORT_BYTES + 1))
    with pytest.raises(ValidationError):
        WriteFileArgs(path="", content="x")
    with pytest.raises(ValidationError):
        WriteFileArgs(path="a.md", content="x", purpose="not-allowed")  # type: ignore[arg-type]
    args = WriteFileArgs(path="a.md", content="x")
    assert args.overwrite is False  # safe default
    assert args.purpose == "report"


# ── 3. Workspace write ──────────────────────────────────────────────────


def test_workspace_write_creates_file_inside_jail(jail, tmp_path):
    audit, ui = FakeAudit(), FakeUI()
    ctx = make_ctx(jail, audit, ui)
    result = asyncio.run(write_file(
        WriteFileArgs(path="reports/out.md", content="# hello"), ctx
    ))
    assert result.startswith("wrote ")
    written = jail.root / "reports" / "out.md"
    assert written.read_text(encoding="utf-8") == "# hello"


# ── 4. Traversal ────────────────────────────────────────────────────────


def test_traversal_rejected_before_any_file_access(jail):
    with pytest.raises(PathPolicyError) as exc:
        resolve_write_target(jail, "../secret.md", external_intent=False)
    assert exc.value.reason_code == "outside_jail"


# ── 5. Symlink escape ───────────────────────────────────────────────────


def test_symlink_escape_rejected(jail, tmp_path):
    outside = tmp_path.parent / "outside-target"
    outside.mkdir(exist_ok=True)
    link = jail.root / "link"
    link.symlink_to(outside)
    with pytest.raises(PathPolicyError) as exc:
        resolve_write_target(jail, "link/escape.md", external_intent=False)
    assert exc.value.reason_code in {"symlink_escape", "outside_jail"}


# ── 6. Sensitive paths ──────────────────────────────────────────────────


@pytest.mark.parametrize("raw", [".env", ".git/hooks/pre-commit", "certs/server.key", "secrets/token"])
def test_sensitive_paths_rejected(jail, raw):
    with pytest.raises(PathPolicyError) as exc:
        resolve_write_target(jail, raw, external_intent=False)
    assert exc.value.reason_code in {"sensitive_path", "invalid_path", "outside_jail"}


# ── 7. Overwrite safety ─────────────────────────────────────────────────


def test_existing_file_not_overwritten_by_default(jail):
    existing = jail.root / "report.md"
    existing.write_text("original", encoding="utf-8")
    audit, ui = FakeAudit(), FakeUI(approved=True)
    ctx = make_ctx(jail, audit, ui)
    result = asyncio.run(write_file(
        WriteFileArgs(path="report.md", content="new"), ctx
    ))
    assert "exists_no_overwrite" in result
    assert existing.read_text(encoding="utf-8") == "original"  # untouched
    assert ui.requests == []  # never even asked — denied by policy first


# ── 8. Atomicity ────────────────────────────────────────────────────────


def test_atomic_write_leaves_no_partial_file_on_failure(jail, monkeypatch):
    target = jail.root / "atomic.md"

    real_replace = os.replace

    def failing_replace(src, dst):
        raise OSError("simulated crash mid-replace")

    monkeypatch.setattr(writefile.os, "replace", failing_replace)
    with pytest.raises(OSError):
        atomic_write_new(target, "content")
    monkeypatch.setattr(writefile.os, "replace", real_replace)

    assert not target.exists()  # no partial/corrupt file
    leftovers = list(jail.root.glob(".tc_wf_*"))
    assert leftovers == []  # temp file cleaned up


# ── 9. Permissions ──────────────────────────────────────────────────────


def test_written_file_has_restricted_permissions(jail):
    target = jail.root / "perm.md"
    meta = atomic_write_new(target, "secret-ish")
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600
    assert meta["bytes"] > 0 and len(meta["sha256"]) == 64


# ── 10. Preview before approval (approval flow) ─────────────────────────


def test_no_write_without_user_approval(jail):
    target = jail.root / "needs-approval.md"
    audit = FakeAudit()
    ui = FakeUI(approved=False)  # user rejects
    ctx = make_ctx(jail, audit, ui)
    # No orchestrator preview/approval flags → handler must ask the UI.
    result = asyncio.run(write_file(
        WriteFileArgs(path="needs-approval.md", content="data"), ctx
    ))
    assert result == "user rejected the write"
    assert not target.exists()
    assert audit.has("write_file_approval")


def test_orchestrator_preview_bypasses_second_prompt_but_still_gated(jail):
    """When the orchestrator granted approval after Safe Preview, the handler
    writes without re-asking — but only because approval was already given."""
    target = jail.root / "previewed.md"
    audit, ui = FakeAudit(), FakeUI(approved=True)
    preview = SimpleNamespace(path=str(target), creates_file=True)
    ctx = make_ctx(
        jail, audit, ui,
        orchestrator_approval_granted=True,
        orchestrator_writefile_preview=preview,
    )
    result = asyncio.run(write_file(
        WriteFileArgs(path="previewed.md", content="data"), ctx
    ))
    assert result.startswith("wrote ")
    assert ui.requests == []  # no second prompt after orchestrator approval
    assert target.exists()


# ── 11. Dissection denial ───────────────────────────────────────────────


def test_dissection_mode_denies_write_file_before_handler_and_preview():
    from termux_coder.core.orchestrator import AgentOrchestrator
    from termux_coder.models.contracts import DecisionKind, ToolCall
    from termux_coder.security.policy import PolicyEngine

    class CountingPreview:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, *a, **k):
            self.calls += 1

        def generate_symbol(self, *a, **k):
            self.calls += 1

        def generate_plan(self, *a, **k):
            self.calls += 1

    class MockRegistry:
        def handler(self, name):
            return None

        def schemas(self):
            return []

    spy_writer = []

    async def fake_write(args, ctx):
        spy_writer.append(True)
        return "should not happen"

    registry_with_tool = MockRegistry()
    registry_with_tool.handler = lambda name: fake_write if name == "write_file" else None

    preview = CountingPreview()
    orch = AgentOrchestrator(
        provider=SimpleNamespace(),
        registry=registry_with_tool,
        policy_engine=PolicyEngine(mode="ASK"),
        audit=FakeAudit(),
        ctx=make_ctx(WorkspaceJail(Path("/tmp")), FakeAudit(), FakeUI()),
        preview_service=preview,
        dissection_mode=True,
    )
    call = ToolCall(
        call_id="c1",
        turn_id="t1",
        name="write_file",
        arguments={"path": "out.md", "content": "x"},
    )
    evaluated = orch._evaluate_call(call)
    assert evaluated.decision == DecisionKind.DENY
    assert "dissection_mode" in evaluated.deny_reason
    assert evaluated.preview is None
    assert preview.calls == 0  # denied BEFORE preview generation
    assert spy_writer == []    # handler never reached


# ── 12. Metadata-only audit ─────────────────────────────────────────────


def test_audit_records_hash_and_path_but_never_content(jail, tmp_path):
    audit, ui = FakeAudit(), FakeUI()
    secret_body = "TOPSECRETBODY-never-log-this"
    ctx = make_ctx(jail, audit, ui)
    asyncio.run(write_file(WriteFileArgs(path="audit-me.md", content=secret_body), ctx))
    result_events = [e for e in audit.events if e["event"] == "write_file_result"]
    assert len(result_events) == 1
    ev = result_events[0]
    assert ev["sha256"] == hashlib.sha256(secret_body.encode()).hexdigest()
    assert ev["bytes"] == len(secret_body.encode())
    assert ev["created"] is True and ev["ok"] is True
    dumped = repr(audit.events)
    assert secret_body not in dumped  # content never logged


# ── 13. SD card gating ──────────────────────────────────────────────────


def test_sd_card_requires_explicit_intent_and_single_folder(jail):
    sd_path = "~/storage/shared/termux-coder/report.md"
    other_sd = "~/storage/shared/other-folder/report.md"

    # Without explicit intent → rejected.
    with pytest.raises(PathPolicyError) as exc:
        resolve_write_target(jail, sd_path, external_intent=False)
    assert exc.value.reason_code == "external_intent_missing"

    # Explicit intent but wrong folder → rejected.
    with pytest.raises(PathPolicyError) as exc:
        resolve_write_target(jail, other_sd, external_intent=True)
    assert exc.value.reason_code == "outside_jail"

    # Explicit intent + allowed folder → accepted.
    resolved, external = resolve_write_target(
        jail, sd_path, external_intent=True
    )
    assert external is True
    assert resolved == Path(sd_path).expanduser().resolve()


def test_sd_intent_detector():
    assert has_external_save_intent("Save the report to ~/storage/shared/termux-coder/x.md")
    assert has_external_save_intent("please save to SD card")
    assert not has_external_save_intent("just analyze the repository")
    assert not has_external_save_intent("write report.md in the workspace")


# ── Spy proof: policy failure ⇒ writer never called ────────────────────


def test_spy_atomic_writer_never_called_when_policy_fails(jail, monkeypatch):
    calls: list[str] = []

    def spy_write(path, content):
        calls.append(str(path))
        return {"bytes": 0, "sha256": "0" * 64}

    monkeypatch.setattr(writefile, "atomic_write_new", spy_write)

    # Traversal attempt → PathPolicyError → writer NOT called.
    with pytest.raises(PathPolicyError):
        resolve_write_target(jail, "../evil.md", external_intent=False)

    audit = FakeAudit()
    ctx = make_ctx(jail, audit, FakeUI())
    asyncio.run(write_file(WriteFileArgs(path="../evil.md", content="x"), ctx))
    assert calls == []  # THE core security property
    assert audit.has("write_file_denied")

    # Missing approval → writer NOT called.
    ctx2 = make_ctx(jail, FakeAudit(), FakeUI(approved=False))
    asyncio.run(write_file(WriteFileArgs(path="ok.md", content="x"), ctx2))
    assert calls == []


# ── 14. Orchestrator integration ─────────────────────────────


def test_evaluated_tool_call_accepts_writefile_preview():
    """EvaluatedToolCall.preview must accept WriteFilePreview (not just PatchPreview).

    This is the core type-compatibility fix: before the fix, assigning a
    WriteFilePreview to EvaluatedToolCall.preview raised a pydantic error.
    """
    from termux_coder.models.contracts import (
        DecisionKind,
        EvaluatedToolCall,
        ToolCall,
        WriteFilePreview,
    )

    call = ToolCall(
        call_id="c1", turn_id="t1", name="write_file",
        arguments={"path": "out.md", "content": "x"},
    )
    preview = WriteFilePreview(
        path="out.md",
        creates_file=True,
        source_hash=None,
        patch_hash="a" * 64,
        result_hash="a" * 64,
        size_bytes=1,
        overwrite=False,
    )
    ec = EvaluatedToolCall(
        call=call,
        decision=DecisionKind.REQUIRE_APPROVAL,
        deny_reason=None,
        preview_error=None,
        preview=preview,
    )
    assert isinstance(ec.preview, WriteFilePreview)


def test_orchestrator_generates_writefile_preview_in_non_dissection_mode(tmp_path):
    """In non-dissection mode, _evaluate_call must produce a WriteFilePreview.

    Verifies: decision is REQUIRE_APPROVAL (not DENY), preview is a
    WriteFilePreview, and source_hash/patch_hash are populated.
    """
    from types import SimpleNamespace
    from termux_coder.core.orchestrator import AgentOrchestrator
    from termux_coder.models.contracts import DecisionKind, ToolCall
    from termux_coder.models.contracts import WriteFilePreview
    from termux_coder.security.policy import PolicyEngine

    jail = WorkspaceJail(tmp_path)
    ctx = make_ctx(jail, FakeAudit(), FakeUI())

    class CountingPreview:
        def __init__(self) -> None:
            self.calls = 0
        def generate(self, *a, **k): self.calls += 1
        def generate_symbol(self, *a, **k): self.calls += 1
        def generate_plan(self, *a, **k): self.calls += 1

    class MockRegistry:
        def handler(self, name): return None
        def schemas(self): return []

    orch = AgentOrchestrator(
        provider=SimpleNamespace(),
        registry=MockRegistry(),
        policy_engine=PolicyEngine(mode="ASK"),
        audit=FakeAudit(),
        ctx=ctx,
        preview_service=CountingPreview(),
        dissection_mode=False,
    )
    orch._user_text = "save the report to report.md"

    call = ToolCall(
        call_id="c1", turn_id="t1", name="write_file",
        arguments={"path": "report.md", "content": "hello"},
    )
    evaluated = orch._evaluate_call(call)
    assert evaluated.decision == DecisionKind.REQUIRE_APPROVAL
    assert isinstance(evaluated.preview, WriteFilePreview)
    assert evaluated.preview.creates_file is True
    assert evaluated.preview.size_bytes == len("hello".encode("utf-8"))
    assert evaluated.preview.source_hash is None  # new file → no source
    assert evaluated.preview.patch_hash == evaluated.preview.result_hash


def test_user_text_propagated_to_ctx_during_execution(tmp_path):
    """The orchestrator must set ctx.user_text before calling the handler,
    so the write_file handler can detect SD-card save intent."""

    from types import SimpleNamespace
    from termux_coder.core.orchestrator import AgentOrchestrator
    from termux_coder.models.contracts import (
        DecisionKind,
        EvaluatedToolCall,
        ToolCall,
    )
    from termux_coder.security.policy import PolicyEngine

    jail = WorkspaceJail(tmp_path)
    captured: list[str] = []

    async def spy_handler(args, ctx):
        captured.append(getattr(ctx, "user_text", "<MISSING>"))
        return "ok"

    class MockRegistry:
        def handler(self, name):
            return spy_handler if name == "write_file" else None
        def schemas(self): return []

    ctx = make_ctx(jail, FakeAudit(), FakeUI())
    orch = AgentOrchestrator(
        provider=SimpleNamespace(),
        registry=MockRegistry(),
        policy_engine=PolicyEngine(mode="ASK"),
        audit=FakeAudit(),
        ctx=ctx,
        dissection_mode=False,
    )
    orch._user_text = "save the report to ~/storage/shared/termux-coder/test.md"

    call = ToolCall(
        call_id="c1", turn_id="t1", name="write_file",
        arguments={"path": "report.md", "content": "x"},
    )
    ecall = EvaluatedToolCall(
        call=call, decision=DecisionKind.ALLOW,
        deny_reason=None, preview_error=None, preview=None,
    )
    asyncio.run(orch._execute_one(ecall))
    assert captured == ["save the report to ~/storage/shared/termux-coder/test.md"]
    # user_text is restored to its pre-execution value (from make_ctx default)
    assert getattr(ctx, "user_text", "<MISSING>") == "save the report"


# ── 15. Adversarial boundary attacks ───────────────────────


def test_absolute_path_outside_sd_rejected(jail):
    """Absolute paths outside the SD-card root must be rejected."""
    with pytest.raises(PathPolicyError) as exc:
        resolve_write_target(jail, "/etc/passwd", external_intent=True)
    assert exc.value.reason_code == "outside_jail"


def test_absolute_non_sd_path_rejected(jail):
    """Absolute path to /tmp must be rejected even with intent."""
    with pytest.raises(PathPolicyError) as exc:
        resolve_write_target(jail, "/tmp/evil.md", external_intent=True)
    assert exc.value.reason_code == "outside_jail"


def test_absolute_sd_subdir_requires_intent(jail):
    """Absolute path inside the SD report dir needs explicit intent."""
    with pytest.raises(PathPolicyError) as exc:
        resolve_write_target(jail, "~/storage/shared/termux-coder/sub/report.md", external_intent=False)
    assert exc.value.reason_code == "external_intent_missing"
    resolved, external = resolve_write_target(jail, "~/storage/shared/termux-coder/sub/report.md", external_intent=True)
    assert external is True


def test_absolute_sd_wrong_folder_rejected(jail):
    """Absolute path in a different SD folder is rejected even with intent."""
    with pytest.raises(PathPolicyError) as exc:
        resolve_write_target(jail, "~/storage/shared/not-termux-coder/report.md", external_intent=True)
    assert exc.value.reason_code == "outside_jail"


def test_normalization_dot_segments_accepted(jail):
    """Relative path with ./ segments should resolve inside the jail."""
    resolved, external = resolve_write_target(jail, "./report.md", external_intent=False)
    assert external is False
    assert resolved == jail.root / "report.md"


def test_traversal_via_normalization_rejected(jail):
    """Path traversal via .. must be rejected even after normalization."""
    for raw in ["../evil.md", "subdir/../../evil.md", "a/b/../../../../evil.md"]:
        with pytest.raises(PathPolicyError) as exc:
            resolve_write_target(jail, raw, external_intent=False)
        assert exc.value.reason_code == "outside_jail"


def test_empty_and_dotdot_only_rejected(jail):
    """Edge cases: empty, whitespace, dot, dotdot."""
    for raw in ["", " ", ".", ".."]:
        with pytest.raises(PathPolicyError):
            resolve_write_target(jail, raw, external_intent=False)


# ── 16. Adversarial symlink attacks ─────────────────────────


def test_symlink_to_file_outside_jail_rejected(jail, tmp_path):
    """A symlink inside the jail pointing to an external file must be rejected."""
    outside = tmp_path.parent / "sym_outside_file"
    outside.write_text("secret", encoding="utf-8")
    link = jail.root / "escape_link"
    link.symlink_to(outside)
    with pytest.raises(PathPolicyError) as exc:
        resolve_write_target(jail, "escape_link", external_intent=False)
    assert exc.value.reason_code in {"symlink_escape", "outside_jail"}


def test_symlink_to_dir_outside_jail_rejected(jail, tmp_path):
    """A symlink to an external directory must be rejected."""
    outside_dir = tmp_path.parent / "sym_outside_dir"
    outside_dir.mkdir(exist_ok=True)
    link = jail.root / "dir_link"
    link.symlink_to(outside_dir)
    with pytest.raises(PathPolicyError) as exc:
        resolve_write_target(jail, "dir_link/evil.md", external_intent=False)
    assert exc.value.reason_code in {"symlink_escape", "outside_jail"}


def test_nested_symlink_escape_rejected(jail, tmp_path):
    """Nested symlinks that eventually escape must be rejected."""
    outside = tmp_path.parent / "nested_outside"
    outside.mkdir(exist_ok=True)
    inner = jail.root / "inner"
    inner.symlink_to(outside)
    outer = jail.root / "outer"
    outer.symlink_to(inner)
    with pytest.raises(PathPolicyError):
        resolve_write_target(jail, "outer/deep/evil.md", external_intent=False)


def test_symlink_escape_via_parent_rejected(jail, tmp_path):
    """Symlink inside a subdir that points outside the jail."""
    outside = tmp_path.parent / "parent_outside"
    outside.write_text("secret", encoding="utf-8")
    subdir = jail.root / "subdir"
    subdir.mkdir()
    link = subdir / "link"
    link.symlink_to(outside)
    with pytest.raises(PathPolicyError) as exc:
        resolve_write_target(jail, "subdir/link", external_intent=False)
    assert exc.value.reason_code in {"symlink_escape", "outside_jail"}


# ── 17. Policy bypass attempts ──────────────────────────────


def test_direct_handler_rejects_traversal(jail):
    """The handler must enforce path policy even without the orchestrator."""
    audit = FakeAudit()
    ui = FakeUI()
    ctx = make_ctx(jail, audit, ui)
    ctx.user_text = "just analyze the repository"
    result = asyncio.run(write_file(
        WriteFileArgs(path="../evil.md", content="x"), ctx
    ))
    assert "refused" in result
    assert audit.has("write_file_denied")


def test_forged_preview_cannot_bypass_path_policy(jail):
    """A forged orchestrator preview must not bypass the handler's own policy."""
    audit = FakeAudit()
    ui = FakeUI(approved=True)
    ctx = make_ctx(jail, audit, ui)
    ctx.orchestrator_writefile_preview = SimpleNamespace(path="../evil.md", creates_file=True)
    ctx.orchestrator_approval_granted = True
    ctx.user_text = "just analyze the repository"
    result = asyncio.run(write_file(
        WriteFileArgs(path="../evil.md", content="x"), ctx
    ))
    assert "refused" in result
    assert audit.has("write_file_denied")


def test_approval_fingerprint_mismatch_rejected():
    """ApprovalGrant rejects when arguments change after approval."""
    from termux_coder.models.contracts import ApprovalGrant, ToolCall

    call = ToolCall(
        call_id="c1", turn_id="t1", name="write_file",
        arguments={"path": "a.md", "content": "x"},
    )
    grant = ApprovalGrant(
        call_id="c1",
        turn_id="t1",
        tool_name="write_file",
        arguments_fingerprint=call.arguments_fingerprint,
    )
    valid, reason = grant.is_valid_for(call)
    assert valid, reason

    mutated = ToolCall(
        call_id="c1", turn_id="t1", name="write_file",
        arguments={"path": "a.md", "content": "y"},
    )
    valid2, reason2 = grant.is_valid_for(mutated)
    assert not valid2
    assert "arguments changed" in reason2.lower()


def test_orchestrator_preview_type_isolation(jail, tmp_path):
    """A WriteFilePreview with a traversal path is still denied by policy inside resolve_write_target."""
    from termux_coder.core.orchestrator import AgentOrchestrator
    from termux_coder.models.contracts import DecisionKind, ToolCall, WriteFilePreview
    from termux_coder.security.policy import PolicyEngine
    from types import SimpleNamespace

    ctx = make_ctx(jail, FakeAudit(), FakeUI())

    class CountingPreview:
        def __init__(self): self.calls = 0
        def generate(self, *a, **k): self.calls += 1
        def generate_symbol(self, *a, **k): self.calls += 1
        def generate_plan(self, *a, **k): self.calls += 1

    class MockRegistry:
        def handler(self, name): return None
        def schemas(self): return []

    orch = AgentOrchestrator(
        provider=SimpleNamespace(),
        registry=MockRegistry(),
        policy_engine=PolicyEngine(mode="ASK"),
        audit=FakeAudit(),
        ctx=ctx,
        preview_service=CountingPreview(),
        dissection_mode=False,
    )
    orch._user_text = "analyze the repo"

    # Traversal path with no write intent → should be DENIED at intent gate
    no_intent_call = ToolCall(
        call_id="c1", turn_id="t1", name="write_file",
        arguments={"path": "../evil.md", "content": "x"},
    )
    eval1 = orch._evaluate_call(no_intent_call)
    assert eval1.decision == DecisionKind.DENY
    assert eval1.preview is None

    # Traversal path WITH write intent → still DENIED at path policy
    orch._user_text = "save the report to ../evil.md"
    traversal_call = ToolCall(
        call_id="c2", turn_id="t1", name="write_file",
        arguments={"path": "../evil.md", "content": "x"},
    )
    eval2 = orch._evaluate_call(traversal_call)
    assert eval2.decision == DecisionKind.DENY
    assert eval2.preview is None


# ── 18. Atomicity failure injection ─────────────────────────


def test_fsync_failure_cleans_up_and_rejects(jail, monkeypatch):
    """If fsync fails, no file is left behind and temp is cleaned."""
    target = jail.root / "fsync_fail.md"

    def failing_fsync(fd):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(writefile.os, "fsync", failing_fsync)
    with pytest.raises(OSError):
        atomic_write_new(target, "content")
    assert not target.exists()
    leftovers = list(jail.root.glob(".tc_wf_*"))
    assert leftovers == []


def test_os_replace_failure_preserves_existing_file(jail, monkeypatch):
    """If os.replace fails, the existing file must be preserved."""
    existing = jail.root / "replace_fail.md"
    existing.write_text("original", encoding="utf-8")

    def failing_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(writefile.os, "replace", failing_replace)
    with pytest.raises(OSError):
        atomic_write_new(existing, "new content")
    assert existing.read_text(encoding="utf-8") == "original"
    leftovers = list(jail.root.glob(".tc_wf_*"))
    assert leftovers == []


def test_atomic_write_never_leaves_partial_content(jail, monkeypatch):
    """A crash during write must not leave a corrupted file."""
    target = jail.root / "partial.md"
    real_write = None

    def crash_after_open(fd, *a, **kw):
        raise OSError("simulated crash after fdopen")

    monkeypatch.setattr(writefile.os, "fdopen", crash_after_open)
    with pytest.raises(OSError):
        atomic_write_new(target, "partial")
    assert not target.exists()
    leftovers = list(jail.root.glob(".tc_wf_*"))
    assert leftovers == []


# ── 19. Audit integrity ─────────────────────────────────────


def test_audit_sha256_matches_written_file(jail):
    """The sha256 recorded in audit must match the actual written file."""
    audit, ui = FakeAudit(), FakeUI()
    ctx = make_ctx(jail, audit, ui)
    content = "verify me please"
    asyncio.run(write_file(WriteFileArgs(path="verify.md", content=content), ctx))
    event = [e for e in audit.events if e["event"] == "write_file_result"]
    assert len(event) == 1
    expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert event[0]["sha256"] == expected
    actual = hashlib.sha256((jail.root / "verify.md").read_bytes()).hexdigest()
    assert actual == expected


def test_audit_denial_uses_classified_reason_code(jail):
    """Denial records use classified reason codes, not raw sensitive paths."""
    audit, ui = FakeAudit(), FakeUI()
    ctx = make_ctx(jail, audit, ui)
    asyncio.run(write_file(WriteFileArgs(path=".env", content="supersecret"), ctx))
    denials = [e for e in audit.events if e["event"] == "write_file_denied"]
    assert len(denials) == 1
    assert denials[0]["reason_code"] == "sensitive_path"
    dump = repr(audit.events)
    assert "supersecret" not in dump


def test_audit_never_logs_content_on_success(jail):
    """Success audit must not contain the written content."""
    audit, ui = FakeAudit(), FakeUI()
    ctx = make_ctx(jail, audit, ui)
    content = "TOPSECRETCOOKIE-secret-value"
    asyncio.run(write_file(WriteFileArgs(path="ok.md", content=content), ctx))
    dump = repr([e for e in audit.events if e["event"] != "write_file_approval"])
    assert "TOPSECRETCOOKIE" not in dump


# ── 20. TOCTOU / race conditions ────────────────────────────


def test_symlink_created_after_resolve_is_rejected(jail, tmp_path):
    """If the target becomes a symlink to outside between resolve and write,
    the handler must still reject it."""
    audit, ui = FakeAudit(), FakeUI(approved=True)
    ctx = make_ctx(jail, audit, ui)
    ctx.user_text = "save the report"

    # Resolve first (validates inside jail)
    resolved, _ = resolve_write_target(jail, "toctou.md", external_intent=False)

    # Replace the resolved path with a symlink to an external file
    outside = tmp_path.parent / "toctou_outside"
    outside.write_text("secret", encoding="utf-8")
    resolved.unlink(missing_ok=True)
    resolved.symlink_to(outside)

    # Handler re-resolves and should catch the symlink escape
    result = asyncio.run(write_file(
        WriteFileArgs(path="toctou.md", content="new"), ctx
    ))
    assert "refused" in result
    assert not outside.read_text(encoding="utf-8") == "new"  # target untouched
