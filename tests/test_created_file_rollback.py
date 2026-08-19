import asyncio
from types import SimpleNamespace

from termux_coder.core.context import SessionState
from termux_coder.security.audit import AuditLog
from termux_coder.security.jail import WorkspaceJail
from termux_coder.tools.edit import (
    ApplyPatchArgs,
    RollbackPatchArgs,
    apply_patch,
    rollback_patch,
)


class ApprovalUI:
    def __init__(self):
        self.requests = []

    async def on_event(self, _kind, **_payload):
        pass

    async def request_approval(self, kind, payload):
        self.requests.append((kind, payload))
        return True


def make_context(tmp_path):
    state = SessionState()
    ui = ApprovalUI()
    ctx = SimpleNamespace(
        jail=WorkspaceJail(tmp_path),
        state=state,
        ui=ui,
        audit=AuditLog(tmp_path / ".termux_coder" / "audit.jsonl"),
        settings=SimpleNamespace(backup_dir=tmp_path / ".termux_coder" / "backups"),
        lsp=None,
    )
    return ctx, state, ui


def test_new_file_patch_can_be_rolled_back(tmp_path):
    async def scenario():
        ctx, state, ui = make_context(tmp_path)
        patch = "<<<<<<< SEARCH\n=======\ncreated = True\n>>>>>>> REPLACE"

        applied = await apply_patch(ApplyPatchArgs(path="created.py", patch=patch), ctx)

        created = tmp_path / "created.py"
        assert applied == "patch applied to created.py"
        assert created.read_text(encoding="utf-8") == "created = True"
        assert state.applied_patches[0]["created"] is True
        assert state.applied_patches[0]["backup"] is None

        rolled_back = await rollback_patch(RollbackPatchArgs(path="created.py"), ctx)

        assert rolled_back == "rollback removed created file created.py"
        assert not created.exists()
        assert "created.py" not in state.read_files
        assert "created.py" not in state.read_hashes
        assert state.applied_patches == []
        assert ui.requests[-1][0] == "rollback"
        assert ui.requests[-1][1]["created"] is True

    asyncio.run(scenario())


def test_existing_file_rollback_restores_backup_and_consumes_record(tmp_path):
    async def scenario():
        ctx, state, _ui = make_context(tmp_path)
        path = tmp_path / "existing.py"
        original = "value = 1\n"
        path.write_text(original, encoding="utf-8")
        state.read_files.add("existing.py")
        import hashlib
        state.read_hashes["existing.py"] = hashlib.sha256(original.encode()).hexdigest()
        patch = "<<<<<<< SEARCH\nvalue = 1\n=======\nvalue = 2\n>>>>>>> REPLACE"

        await apply_patch(ApplyPatchArgs(path="existing.py", patch=patch), ctx)
        assert path.read_text(encoding="utf-8") == "value = 2\n"

        rolled_back = await rollback_patch(RollbackPatchArgs(path="existing.py"), ctx)

        assert rolled_back.startswith("rollback applied to existing.py from ")
        assert path.read_text(encoding="utf-8") == original
        assert state.applied_patches == []
        assert state.read_hashes["existing.py"] == hashlib.sha256(original.encode()).hexdigest()

    asyncio.run(scenario())
