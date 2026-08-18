from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

from termux_coder.core.context import SessionState
from termux_coder.security.audit import AuditLog
from termux_coder.security.jail import WorkspaceJail
from termux_coder.tools import transaction
from termux_coder.tools.preview import PatchPreviewService


class _Settings:
    def __init__(self, backup_dir: Path):
        self.backup_dir = backup_dir


class _UI:
    def __init__(self, approve: bool = True):
        self.approve = approve
        self.approvals: list[tuple[str, dict]] = []
        self.events: list[tuple[str, dict]] = []

    async def request_approval(self, kind: str, payload: dict) -> bool:
        self.approvals.append((kind, payload))
        return self.approve

    async def on_event(self, kind: str, **payload) -> None:
        self.events.append((kind, payload))


def _patch(old: str, new: str) -> str:
    return f"<<<<<<< SEARCH\n{old}\n=======\n{new}\n>>>>>>> REPLACE"


def _ctx(workspace: Path, *paths: str):
    state = SessionState()
    for rel in paths:
        text = (workspace / rel).read_text(encoding="utf-8")
        state.read_files.add(rel)
        state.read_hashes[rel] = hashlib.sha256(text.encode()).hexdigest()
    ui = _UI()
    return SimpleNamespace(
        jail=WorkspaceJail(workspace),
        state=state,
        settings=_Settings(workspace / ".termux_coder" / "backups"),
        ui=ui,
        audit=AuditLog(workspace / ".termux_coder" / "audit.jsonl"),
    )


def test_patch_plan_applies_multiple_files_once(tmp_path):
    (tmp_path / "a.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("b = 2\n", encoding="utf-8")
    ctx = _ctx(tmp_path, "a.py", "b.py")
    args = transaction.PatchPlanArgs(
        summary="update both values",
        operations=[
            transaction.PatchOperationArgs(path="a.py", patch=_patch("a = 1", "a = 10")),
            transaction.PatchOperationArgs(path="b.py", patch=_patch("b = 2", "b = 20")),
        ],
    )

    result = asyncio.run(transaction.apply_patch_plan(args, ctx))

    assert result.startswith("patch plan applied:")
    assert (tmp_path / "a.py").read_text() == "a = 10\n"
    assert (tmp_path / "b.py").read_text() == "b = 20\n"
    assert len(ctx.ui.approvals) == 1
    assert ctx.ui.approvals[0][0] == "patch_plan"
    assert len(ctx.state.applied_patches) == 2


def test_patch_plan_rejects_before_writing_if_one_operation_is_invalid(tmp_path):
    (tmp_path / "a.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("b = 2\n", encoding="utf-8")
    ctx = _ctx(tmp_path, "a.py", "b.py")
    args = transaction.PatchPlanArgs(
        operations=[
            transaction.PatchOperationArgs(path="a.py", patch=_patch("a = 1", "a = 10")),
            transaction.PatchOperationArgs(path="b.py", patch=_patch("missing", "b = 20")),
        ]
    )

    result = asyncio.run(transaction.apply_patch_plan(args, ctx))

    assert result.startswith("patch plan refused:")
    assert (tmp_path / "a.py").read_text() == "a = 1\n"
    assert (tmp_path / "b.py").read_text() == "b = 2\n"
    assert ctx.state.applied_patches == []
    assert ctx.ui.approvals == []


def test_patch_plan_rolls_back_files_when_second_write_fails(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("b = 2\n", encoding="utf-8")
    ctx = _ctx(tmp_path, "a.py", "b.py")
    args = transaction.PatchPlanArgs(
        operations=[
            transaction.PatchOperationArgs(path="a.py", patch=_patch("a = 1", "a = 10")),
            transaction.PatchOperationArgs(path="b.py", patch=_patch("b = 2", "b = 20")),
        ]
    )
    original_write = transaction._atomic_write

    def fail_b(path, content, original_mode=None):
        if Path(path).name == "b.py":
            raise OSError("simulated second-file write failure")
        return original_write(path, content, original_mode)

    monkeypatch.setattr(transaction, "_atomic_write", fail_b)

    result = asyncio.run(transaction.apply_patch_plan(args, ctx))

    assert result.startswith("patch plan failed and was rolled back:")
    assert (tmp_path / "a.py").read_text() == "a = 1\n"
    assert (tmp_path / "b.py").read_text() == "b = 2\n"
    assert ctx.state.applied_patches == []


def test_patch_plan_rollback_restores_all_files(tmp_path):
    (tmp_path / "a.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("b = 2\n", encoding="utf-8")
    ctx = _ctx(tmp_path, "a.py", "b.py")
    args = transaction.PatchPlanArgs(
        operations=[
            transaction.PatchOperationArgs(path="a.py", patch=_patch("a = 1", "a = 10")),
            transaction.PatchOperationArgs(path="b.py", patch=_patch("b = 2", "b = 20")),
        ]
    )

    apply_result = asyncio.run(transaction.apply_patch_plan(args, ctx))
    plan_id = apply_result.split()[3]
    rollback_result = asyncio.run(
        transaction.rollback_patch_plan(
            transaction.RollbackPlanArgs(plan_id=plan_id), ctx
        )
    )

    assert rollback_result == f"patch plan rollback applied: {plan_id}"
    assert (tmp_path / "a.py").read_text() == "a = 1\n"
    assert (tmp_path / "b.py").read_text() == "b = 2\n"
    assert ctx.state.applied_patches == []
