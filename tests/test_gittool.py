import asyncio
from types import SimpleNamespace

from termux_coder.security.audit import AuditLog
from termux_coder.security.jail import WorkspaceJail
from termux_coder.tools import gittool


class FakeUI:
    def __init__(self, approve=True):
        self.approve = approve
        self.events = []

    async def on_event(self, kind, **payload):
        self.events.append((kind, payload))

    async def request_approval(self, kind, payload):
        return self.approve


def make_ctx(tmp_path, approve=True):
    return SimpleNamespace(
        jail=WorkspaceJail(tmp_path),
        settings=SimpleNamespace(max_output_chars=4000),
        state=SimpleNamespace(),
        ui=FakeUI(approve),
        audit=AuditLog(tmp_path / ".termux_coder" / "audit.jsonl"),
        policy=SimpleNamespace(),
        repomap=None,
    )


def test_not_repo_then_init(tmp_path):
    ctx = make_ctx(tmp_path)
    assert "not a git repository" in asyncio.run(gittool.git_status({}, ctx))
    out = asyncio.run(gittool.git_init({}, ctx))
    assert "Initialized" in out or "initialized" in out


def test_checkpoint_commit_restore_flow(tmp_path):
    ctx = make_ctx(tmp_path)
    asyncio.run(gittool.git_init({}, ctx))

    (tmp_path / "a.py").write_text("x = 1\n")
    assert "checkpoint" in asyncio.run(gittool.git_checkpoint({}, ctx))
    assert "clean" in asyncio.run(gittool.git_checkpoint({}, ctx))

    (tmp_path / "a.py").write_text("x = 2\n")
    out = asyncio.run(gittool.git_commit({"message": "update x"}, ctx))
    assert out.startswith("committed ")

    log = asyncio.run(gittool.git_log({}, ctx))
    assert "agent: update x" in log  # البادئة إلزامية

    (tmp_path / "a.py").write_text("x = 999\n")
    assert "restored" in asyncio.run(gittool.git_restore({"paths": ["a.py"]}, ctx))
    assert (tmp_path / "a.py").read_text() == "x = 2\n"


def test_rejected_restore_keeps_file(tmp_path):
    ctx = make_ctx(tmp_path, approve=True)
    asyncio.run(gittool.git_init({}, ctx))
    (tmp_path / "a.py").write_text("v1\n")
    asyncio.run(gittool.git_checkpoint({}, ctx))

    ctx.ui.approve = False
    (tmp_path / "a.py").write_text("v2\n")
    out = asyncio.run(gittool.git_restore({"paths": ["a.py"]}, ctx))
    assert "rejected" in out
    assert (tmp_path / "a.py").read_text() == "v2\n"


def test_restore_path_jail(tmp_path):
    ctx = make_ctx(tmp_path)
    asyncio.run(gittool.git_init({}, ctx))
    out = asyncio.run(gittool.git_restore({"paths": ["../evil"]}, ctx))
    assert "restore error" in out
