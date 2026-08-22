"""
Forensic Security Tests for DISSECTION-04

Tests Direct Handler Bypass, Symlink Traversal, Atomicity, Audit Integrity,
and TOCTOU scenarios against the write_file tool.

All tests are BLACK-BOX — they invoke the public API and verify security
properties. No source files are modified.
"""
import asyncio
import hashlib
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from termux_coder.tools.writefile import (
    WriteFileArgs,
    PathPolicyError,
    atomic_write_new,
    resolve_write_target,
    write_file,
    _reject_symlink_escape,
)
from termux_coder.security.jail import WorkspaceJail, JailViolation


# ── Minimal test helpers (self-contained) ────────────────────

class MiniAudit:
    """Capture audit.log() calls without writing to disk."""
    def __init__(self):
        self.events: list[dict] = []
    def log(self, event: str, **data) -> None:
        self.events.append({"event": event, **data})
    def has(self, event: str) -> bool:
        return any(e["event"] == event for e in self.events)
    def all_text(self) -> str:
        return repr(self.events)


class MiniUI:
    """Fake UI that tracks approval requests and events."""
    def __init__(self, approved: bool = False):
        self.approved = approved
        self.approval_requests: list[dict] = []
        self.events: list[dict] = []
    async def request_approval(self, kind: str, payload: dict) -> bool:
        self.approval_requests.append({"kind": kind, "payload": payload})
        return self.approved
    async def on_event(self, kind: str, **data) -> None:
        self.events.append({"kind": kind, **data})
        return None


def make_forged_ctx(jail, audit, ui, *, approved=True, user_text="", **kwargs):
    """Create a ToolContext-like SimpleNamespace with forged approval flags."""
    return SimpleNamespace(
        jail=jail,
        settings=SimpleNamespace(max_file_chars=100_000),
        state=SimpleNamespace(
            read_files=set(), read_hashes={}, applied_patches=[],
        ),
        ui=ui,
        audit=audit,
        user_text=user_text,
        orchestrator_approval_granted=approved,
        orchestrator_writefile_preview=None,
        **kwargs,
    )


# ── Section 1: Direct Handler Bypass ─────────────────────────

class TestDirectHandlerBypass:
    """
    The handler checks ctx.orchestrator_approval_granted via getattr().
    When True (set by orchestrator after Safe Preview + user consent),
    the handler skips its own UI request_approval call.

    If write_file is invoked outside the orchestrator with a forged ctx,
    the approval UI is bypassed — path policy still enforced.
    """

    def test_path_policy_enforced_with_forged_approval(self, tmp_path):
        """Outside-jail path rejected even with forged approval=True."""
        jail = WorkspaceJail(tmp_path)
        audit = MiniAudit()
        ui = MiniUI(approved=True)
        ctx = make_forged_ctx(jail, audit, ui)
        result = asyncio.run(write_file(
            WriteFileArgs(path="/etc/evil.txt", content="data"), ctx
        ))
        assert "refused" in result
        assert "outside_jail" in result
        assert ui.approval_requests == []

    def test_silent_approval_for_new_file_inside_jail(self, tmp_path):
        """Forged approval=True skips the UI prompt for new files inside jail.

        [OBSERVED] Context Trust vulnerability: direct invocation bypasses
        user consent while still enforcing path policy.
        """
        jail = WorkspaceJail(tmp_path)
        audit = MiniAudit()
        ui = MiniUI(approved=True)
        ctx = make_forged_ctx(jail, audit, ui, user_text="save the report")
        result = asyncio.run(write_file(
            WriteFileArgs(path="forged_report.md", content="silent data"), ctx
        ))
        assert "wrote" in result
        assert ui.approval_requests == []
        assert (tmp_path / "forged_report.md").read_text() == "silent data"
        assert audit.has("write_file_result")

    def test_silent_overwrite_bypasses_confirmation(self, tmp_path):
        """Forged approval=True bypasses overwrite confirmation."""
        jail = WorkspaceJail(tmp_path)
        existing = tmp_path / "existing.md"
        existing.write_text("original", encoding="utf-8")
        audit = MiniAudit()
        ui = MiniUI(approved=True)
        ctx = make_forged_ctx(jail, audit, ui, user_text="save the report")
        result = asyncio.run(write_file(
            WriteFileArgs(path="existing.md", content="replaced", overwrite=True), ctx
        ))
        assert "wrote" in result
        assert ui.approval_requests == []
        assert existing.read_text(encoding="utf-8") == "replaced"

    def test_external_intent_still_enforced_with_forged_approval(self, tmp_path):
        """Forged approval cannot bypass external intent for SD-card paths."""
        jail = WorkspaceJail(tmp_path)
        audit = MiniAudit()
        ui = MiniUI(approved=True)
        ctx = make_forged_ctx(jail, audit, ui, user_text="just browse")
        result = asyncio.run(write_file(
            WriteFileArgs(
                path="~/storage/shared/termux-coder/escape.md",
                content="data",
            ), ctx
        ))
        assert "refused" in result
        assert "external_intent_missing" in result
        assert ui.approval_requests == []


# ── Section 2: Symlink Traversal ────────────────────────────

class TestSymlinkTraversal:
    """
    Threat: symlinks inside the workspace that point outside could be used
    to write to arbitrary filesystem locations.

    Defense layers in resolve_write_target:
      1. jail.check() → resolve() + is_relative_to()
      2. _reject_sensitive() → blocks .git, .env, .key, etc.
      3. _reject_symlink_escape() → TOCTOU defense, walks parents
    """

    def test_symlink_to_outside_directory_rejected(self, tmp_path):
        """A symlink inside jail → external directory must be rejected."""
        jail = WorkspaceJail(tmp_path)
        outside = tmp_path.parent / "outside_secret_dir"
        outside.mkdir(exist_ok=True)
        link = tmp_path / "escape_link"
        link.symlink_to(outside)
        with pytest.raises(PathPolicyError) as exc:
            resolve_write_target(jail, "escape_link/evil.md", external_intent=False)
        assert exc.value.reason_code in {"outside_jail", "symlink_escape"}

    def test_symlink_to_outside_file_rejected(self, tmp_path):
        """A symlink inside jail → external file must be rejected."""
        jail = WorkspaceJail(tmp_path)
        outside_file = tmp_path.parent / "outside_secret_file"
        outside_file.write_text("secret", encoding="utf-8")
        link = tmp_path / "escape_file"
        link.symlink_to(outside_file)
        with pytest.raises(PathPolicyError) as exc:
            resolve_write_target(jail, "escape_file", external_intent=False)
        assert exc.value.reason_code in {"outside_jail", "symlink_escape"}

    def test_nested_symlink_chain_escape_rejected(self, tmp_path):
        """Nested symlinks (link→link→outside) must be rejected."""
        jail = WorkspaceJail(tmp_path)
        outside = tmp_path.parent / "deep_outside"
        outside.mkdir(exist_ok=True)
        inner = tmp_path / "inner"
        inner.symlink_to(outside)
        outer = tmp_path / "outer"
        outer.symlink_to(inner)
        with pytest.raises(PathPolicyError) as exc:
            resolve_write_target(jail, "outer/evil.md", external_intent=False)
        assert exc.value.reason_code in {"outside_jail", "symlink_escape"}

    def test_startswith_sibling_prefix_not_bypassed(self, tmp_path):
        """The startswith() check in _reject_symlink_escape uses os.sep suffix,
        so /base_evil is NOT confused with /base.

        Without the os.sep suffix, "/base_evil".startswith("/base") would
        return True — a security bypass. With the suffix, the check is safe.
        This test confirms the current code is NOT vulnerable.
        """
        base = tmp_path / "base"
        base.mkdir()
        sibling = tmp_path / "base_evil"
        sibling.mkdir()
        link = base / "escape"
        link.symlink_to(sibling)
        with pytest.raises(PathPolicyError) as exc:
            _reject_symlink_escape(link)
        assert exc.value.reason_code == "symlink_escape"

    def test_symlink_within_jail_allowed(self, tmp_path):
        """A symlink that points within the jail should NOT be rejected."""
        jail = WorkspaceJail(tmp_path)
        inside_dir = tmp_path / "inner_dir"
        inside_dir.mkdir()
        inside_file = inside_dir / "file.md"
        inside_file.write_text("ok", encoding="utf-8")
        link = tmp_path / "link_to_inner"
        link.symlink_to(inside_dir)
        resolved = (tmp_path / "link_to_inner" / "file.md").resolve()
        _reject_symlink_escape(resolved)  # must NOT raise

    def test_symlink_escape_through_handler_rejected(self, tmp_path):
        """End-to-end: write_file handler rejects a path through a symlink
        to an external location."""
        jail = WorkspaceJail(tmp_path)
        outside = tmp_path.parent / "handler_escape"
        outside.write_text("original", encoding="utf-8")
        link = tmp_path / "escape_link"
        link.symlink_to(outside)
        audit = MiniAudit()
        ui = MiniUI(approved=True)
        ctx = make_forged_ctx(jail, audit, ui, user_text="save the report")
        result = asyncio.run(write_file(
            WriteFileArgs(path="escape_link", content="evil"), ctx
        ))
        assert "refused" in result
        assert outside.read_text(encoding="utf-8") == "original"
        assert audit.has("write_file_denied")


# ── Section 3: Atomicity Failure Injection ──────────────────

class TestAtomicityFailures:
    """
    Threat: if the write crashes mid-operation (fsync failure, os.replace
    failure, disk full), the filesystem must not be left inconsistent.
    """

    def test_fsync_failure_leaves_no_file(self, tmp_path, monkeypatch):
        """If fsync raises OSError, no file is created and temp is cleaned."""
        from termux_coder.tools import writefile as wf_module
        target = tmp_path / "crash.md"
        def failing_fsync(fd):
            raise OSError("simulated fsync failure")
        monkeypatch.setattr(wf_module.os, "fsync", failing_fsync)
        with pytest.raises(OSError):
            atomic_write_new(target, "content")
        assert not target.exists()
        leftovers = list(tmp_path.glob(".tc_wf_*"))
        assert leftovers == []

    def test_os_replace_failure_preserves_existing(self, tmp_path, monkeypatch):
        """If os.replace fails, the existing file must be untouched."""
        from termux_coder.tools import writefile as wf_module
        existing = tmp_path / "replace_fail.md"
        existing.write_text("original", encoding="utf-8")
        def failing_replace(src, dst):
            raise OSError("simulated replace failure")
        monkeypatch.setattr(wf_module.os, "replace", failing_replace)
        with pytest.raises(OSError):
            atomic_write_new(existing, "should not persist")
        assert existing.read_text(encoding="utf-8") == "original"
        leftovers = list(tmp_path.glob(".tc_wf_*"))
        assert leftovers == []

    def test_mkstemp_failure_propagates(self, tmp_path, monkeypatch):
        """If mkstemp fails, the error propagates and no file is created."""
        from termux_coder.tools import writefile as wf_module
        target = tmp_path / "no_space.md"
        def failing_mkstemp(*args, **kwargs):
            raise OSError("disk full")
        monkeypatch.setattr(wf_module.tempfile, "mkstemp", failing_mkstemp)
        with pytest.raises(OSError):
            atomic_write_new(target, "content")
        assert not target.exists()

    def test_file_permissions_are_restricted(self, tmp_path):
        """New files must have 0600 permissions (owner read/write only)."""
        target = tmp_path / "perms.md"
        atomic_write_new(target, "content")
        mode = stat.S_IMODE(target.stat().st_mode)
        assert not (mode & stat.S_IROTH)
        assert not (mode & stat.S_IWOTH)
        assert not (mode & stat.S_IXOTH)
        assert mode & stat.S_IRUSR
        assert mode & stat.S_IWUSR


# ── Section 4: Audit Integrity ──────────────────────────────

class TestAuditIntegrity:
    """
    Threat: the audit log must never contain file content, secrets, or
    sensitive data. Records only metadata: path, size, hash, classified
    reason codes.
    """

    def test_audit_result_sha256_matches_file(self, tmp_path):
        """The sha256 recorded in audit must match the actual written file."""
        jail = WorkspaceJail(tmp_path)
        audit = MiniAudit()
        ui = MiniUI(approved=True)
        ctx = make_forged_ctx(jail, audit, ui, user_text="save the report")
        content = "verify me"
        asyncio.run(write_file(
            WriteFileArgs(path="verify.md", content=content), ctx
        ))
        result_event = [e for e in audit.events if e["event"] == "write_file_result"][0]
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        actual = hashlib.sha256((tmp_path / "verify.md").read_bytes()).hexdigest()
        assert result_event["sha256"] == expected
        assert actual == expected

    def test_audit_never_contains_content(self, tmp_path):
        """Brute-force: scan every audit event field for content leakage."""
        jail = WorkspaceJail(tmp_path)
        audit = MiniAudit()
        ui = MiniUI(approved=True)
        ctx = make_forged_ctx(jail, audit, ui, user_text="save the report")
        marker = "UNIQUE_MARKER_LEAK_CHECK_98765"
        asyncio.run(write_file(
            WriteFileArgs(path="check.md", content=marker), ctx
        ))
        for event in audit.events:
            for key, value in event.items():
                if isinstance(value, str):
                    assert marker not in value, (
                        f"Content leaked into audit event {event['event']}.{key}"
                    )

    def test_audit_denial_uses_classified_reason_code(self, tmp_path):
        """Audit denials record classified reason_code, not raw exception text."""
        jail = WorkspaceJail(tmp_path)
        audit = MiniAudit()
        ui = MiniUI(approved=True)
        ctx = make_forged_ctx(jail, audit, ui, user_text="just browse")
        asyncio.run(write_file(
            WriteFileArgs(path=".env", content="secret_token_here"), ctx
        ))
        denials = [e for e in audit.events if e["event"] == "write_file_denied"]
        assert len(denials) == 1
        assert denials[0]["reason_code"] == "sensitive_path"
        assert "secret_token_here" not in audit.all_text()

    def test_audit_traversal_denial_no_content_leak(self, tmp_path):
        """write_file_denied for traversal contains only args.path, not content."""
        jail = WorkspaceJail(tmp_path)
        audit = MiniAudit()
        ui = MiniUI(approved=True)
        ctx = make_forged_ctx(jail, audit, ui, user_text="just analyze")
        asyncio.run(write_file(
            WriteFileArgs(path="../../etc/passwd", content="leaked_secret"), ctx
        ))
        denials = [e for e in audit.events if e["event"] == "write_file_denied"]
        assert len(denials) == 1
        assert denials[0]["reason_code"] == "outside_jail"
        assert "leaked_secret" not in audit.all_text()


# ── Section 5: TOCTOU / Race ────────────────────────────────

class TestTOCTOU:
    """
    Threat: a symlink could be created or replaced between
    resolve_write_target() and atomic_write_new().

    The handler re-validates the path on every call, so a symlink created
    between the orchestrator's preview and the handler's execution is caught
    on re-resolution.
    """

    def test_symlink_created_after_resolve_rejected(self, tmp_path):
        """Symlink at target after initial resolve is re-caught by handler."""
        jail = WorkspaceJail(tmp_path)
        audit = MiniAudit()
        ui = MiniUI(approved=True)
        ctx = make_forged_ctx(jail, audit, ui, user_text="just analyze the code")
        target = tmp_path / "toctou.md"

        # Initial resolve succeeds (no symlink yet)
        resolved, _ = resolve_write_target(jail, "toctou.md", external_intent=False)

        # Replace target with a symlink to outside
        target.unlink(missing_ok=True)
        outside = tmp_path.parent / "toctou_outside"
        outside.write_text("secret", encoding="utf-8")
        target.symlink_to(outside)

        # Handler re-resolves from args.path → should reject
        result = asyncio.run(write_file(
            WriteFileArgs(path="toctou.md", content="evil"), ctx
        ))
        assert "refused" in result
        assert outside.read_text(encoding="utf-8") == "secret"
        assert audit.has("write_file_denied")

    def test_symlink_in_parent_after_resolve_caught(self, tmp_path):
        """If a parent dir becomes a symlink after initial resolve,
        _reject_symlink_escape should detect it."""
        jail = WorkspaceJail(tmp_path)
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        resolved_path = jail.check_writable_dir("subdir/report.md")
        assert resolved_path.is_relative_to(jail.root)

        # Replace subdir with a symlink to outside
        subdir.rmdir()
        outside = tmp_path.parent / "parent_escape"
        outside.mkdir(exist_ok=True)
        subdir.symlink_to(outside)

        with pytest.raises(PathPolicyError) as exc:
            _reject_symlink_escape(resolved_path)
        assert exc.value.reason_code == "symlink_escape"

    def test_no_partial_file_after_crash(self, tmp_path, monkeypatch):
        """If atomic_write_new fails, no .tc_wf_* temp file remains."""
        from termux_coder.tools import writefile as wf_module
        target = tmp_path / "atomic_fail.md"
        existing = tmp_path / "keep.md"
        existing.write_text("original", encoding="utf-8")
        monkeypatch.setattr(wf_module.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("fail")))
        with pytest.raises(OSError):
            atomic_write_new(target, "content")
        leftovers = list(tmp_path.glob(".tc_wf_*"))
        assert leftovers == []
        assert existing.read_text(encoding="utf-8") == "original"
