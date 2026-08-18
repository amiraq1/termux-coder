from __future__ import annotations

import pytest

from termux_coder.core.context import SessionState
from termux_coder.core.orchestrator import AgentOrchestrator
from termux_coder.models.contracts import ApprovalGrant, EvaluatedToolCall, DecisionKind, ToolCall
from termux_coder.security.jail import WorkspaceJail
from termux_coder.tools.preview import PatchPreview, PatchPreviewService, PreviewError


def _patch(old: str, new: str) -> str:
    return f"<<<<<<< SEARCH\n{old}\n=======\n{new}\n>>>>>>> REPLACE"


def test_preview_uses_real_patch_engine_and_returns_diff(tmp_path):
    path = tmp_path / "main.py"
    path.write_text("x = 1\n", encoding="utf-8")
    state = SessionState(read_files={"main.py"}, read_hashes={"main.py": ""})
    # محاكاة hash القراءة الحقيقي
    import hashlib
    state.read_hashes["main.py"] = hashlib.sha256(b"x = 1\n").hexdigest()

    preview = PatchPreviewService(WorkspaceJail(tmp_path), state).generate(
        "main.py", _patch("x = 1", "x = 2")
    )

    assert preview.path == "main.py"
    assert "-x = 1" in preview.diff
    assert "+x = 2" in preview.diff
    assert preview.source_hash != preview.result_hash
    assert preview.additions == 1
    assert preview.removals == 1


def test_preview_rejects_existing_file_not_read(tmp_path):
    path = tmp_path / "main.py"
    path.write_text("x = 1\n", encoding="utf-8")
    service = PatchPreviewService(WorkspaceJail(tmp_path), SessionState())

    with pytest.raises(PreviewError, match="must read_file"):
        service.generate("main.py", _patch("x = 1", "x = 2"))


def test_preview_rejects_ambiguous_search(tmp_path):
    path = tmp_path / "main.py"
    path.write_text("x = 1\nx = 1\n", encoding="utf-8")
    import hashlib
    state = SessionState(
        read_files={"main.py"},
        read_hashes={"main.py": hashlib.sha256(path.read_bytes()).hexdigest()},
    )

    with pytest.raises(PreviewError, match="ambiguous"):
        PatchPreviewService(WorkspaceJail(tmp_path), state).generate(
            "main.py", _patch("x = 1", "x = 2")
        )


def test_approval_grant_binds_preview_fingerprints(tmp_path):
    path = tmp_path / "main.py"
    path.write_text("x = 1\n", encoding="utf-8")
    import hashlib
    state = SessionState(
        read_files={"main.py"},
        read_hashes={"main.py": hashlib.sha256(path.read_bytes()).hexdigest()},
    )
    preview = PatchPreviewService(WorkspaceJail(tmp_path), state).generate(
        "main.py", _patch("x = 1", "x = 2")
    )
    call = ToolCall(
        call_id="c1", turn_id="t1", name="apply_patch",
        arguments={"path": "main.py", "patch": _patch("x = 1", "x = 2")},
    )
    grant = ApprovalGrant(
        call_id="c1", turn_id="t1", tool_name="apply_patch",
        arguments_fingerprint=call.arguments_fingerprint,
        preview_source_hash=preview.source_hash,
        preview_patch_hash=preview.patch_hash,
        preview_result_hash=preview.result_hash,
    )
    assert grant.is_valid_for(call, preview) == (True, "")
    changed = preview.model_copy(update={"result_hash": "0" * 64})
    valid, reason = grant.is_valid_for(call, changed)
    assert not valid
    assert "result hash" in reason


def test_approval_payload_uses_preview_diff_not_raw_patch():
    preview = PatchPreview(
        path="main.py",
        diff="--- a/main.py\n+++ b/main.py\n-x = 1\n+x = 2\n",
        source_hash="1" * 64,
        patch_hash="2" * 64,
        result_hash="3" * 64,
        additions=1,
        removals=1,
    )
    call = ToolCall(
        call_id="c1", turn_id="t1", name="apply_patch",
        arguments={"path": "main.py", "patch": "raw search replace"},
    )
    evaluated = EvaluatedToolCall(
        call=call, decision=DecisionKind.REQUIRE_APPROVAL, preview=preview
    )
    payload = AgentOrchestrator._approval_payload(evaluated)
    assert payload["diff"] == preview.diff
    assert payload["additions"] == 1
    assert payload["removals"] == 1
