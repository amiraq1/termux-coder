"""Tests for WorkspaceJail security boundaries."""
from __future__ import annotations

import os
import stat

import pytest

from termux_coder.security.jail import JailViolation, WorkspaceJail


# ── أساسيات ──────────────────────────────────────────────────

def test_inside_workspace(tmp_path):
    jail = WorkspaceJail(tmp_path)
    (tmp_path / "project").mkdir()
    assert jail.check("project/x.py").is_relative_to(tmp_path)


def test_relative_path_resolved(tmp_path):
    (tmp_path / "src").mkdir()
    jail = WorkspaceJail(tmp_path)
    result = jail.check("src")
    assert result == (tmp_path / "src").resolve()


def test_sibling_prefix_is_blocked(tmp_path):
    # /project مقابل /project2
    (tmp_path / "project").mkdir()
    (tmp_path / "project2").mkdir()
    jail = WorkspaceJail(tmp_path / "project")
    with pytest.raises(JailViolation):
        jail.check(str(tmp_path / "project2" / "evil.py"))


def test_dotdot_is_blocked(tmp_path):
    jail = WorkspaceJail(tmp_path)
    with pytest.raises(JailViolation):
        jail.check("../etc/passwd")


def test_dotdot_deep_is_blocked(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    jail = WorkspaceJail(tmp_path)
    with pytest.raises(JailViolation):
        jail.check("a/b/../../../../../../etc/passwd")


def test_absolute_path_inside_workspace_is_allowed(tmp_path):
    """المسار المطلق الواقع داخل الـ workspace مسموح به."""
    jail = WorkspaceJail(tmp_path)
    (tmp_path / "file.txt").write_text("x")
    result = jail.check(str(tmp_path / "file.txt"))
    assert result == (tmp_path / "file.txt").resolve()


def test_absolute_path_outside_workspace_is_blocked(tmp_path):
    jail = WorkspaceJail(tmp_path)
    with pytest.raises(JailViolation):
        jail.check("/etc/passwd")


def test_empty_path_is_workspace_root(tmp_path):
    jail = WorkspaceJail(tmp_path)
    # المسار الفارغ يحل إلى root
    result = jail.check("")
    assert result == tmp_path.resolve()


# ── الروابط الرمزية ───────────────────────────────────────────

def test_symlink_inside_workspace_is_allowed(tmp_path):
    """رابط رمزي يشير لملف داخل الـ workspace: مسموح."""
    (tmp_path / "ws").mkdir()
    target = tmp_path / "ws" / "real.txt"
    target.write_text("hello")
    link = tmp_path / "ws" / "link.txt"
    link.symlink_to(target)
    jail = WorkspaceJail(tmp_path / "ws")
    result = jail.check("link.txt")
    assert result == target.resolve()


def test_symlink_escape_is_blocked(tmp_path):
    """رابط رمزي يهرب خارج الـ workspace: محظور."""
    (tmp_path / "ws").mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    link = tmp_path / "ws" / "link.txt"
    link.symlink_to(outside)
    jail = WorkspaceJail(tmp_path / "ws")
    with pytest.raises(JailViolation):
        jail.check("link.txt")


def test_symlink_to_dir_outside_blocked(tmp_path):
    (tmp_path / "ws").mkdir()
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    link = tmp_path / "ws" / "link_dir"
    link.symlink_to(outside_dir)
    jail = WorkspaceJail(tmp_path / "ws")
    with pytest.raises(JailViolation):
        jail.check("link_dir/evil.py")


# ── check_readable ───────────────────────────────────────────────

def test_check_readable_regular_file(tmp_path):
    jail = WorkspaceJail(tmp_path)
    f = tmp_path / "a.py"
    f.write_text("print('hello')")
    result = jail.check_readable("a.py")
    assert result == f.resolve()


def test_check_readable_rejects_directory(tmp_path):
    jail = WorkspaceJail(tmp_path)
    (tmp_path / "mydir").mkdir()
    with pytest.raises(JailViolation, match="directory"):
        jail.check_readable("mydir")


def test_check_readable_rejects_missing_file(tmp_path):
    jail = WorkspaceJail(tmp_path)
    with pytest.raises(JailViolation, match="does not exist"):
        jail.check_readable("nonexistent.py")


def test_check_readable_rejects_binary_file(tmp_path):
    jail = WorkspaceJail(tmp_path)
    binary_file = tmp_path / "lib.so"
    binary_file.write_bytes(b"\x7fELF\x00" + b"a" * 100)
    with pytest.raises(JailViolation, match="binary"):
        jail.check_readable("lib.so")


def test_check_readable_text_file_with_null_rejected(tmp_path):
    jail = WorkspaceJail(tmp_path)
    f = tmp_path / "weird.txt"
    f.write_bytes(b"hello\x00world")
    with pytest.raises(JailViolation, match="binary"):
        jail.check_readable("weird.txt")


# ── check_writable_dir ──────────────────────────────────────────

def test_check_writable_dir_inside_workspace(tmp_path):
    jail = WorkspaceJail(tmp_path)
    result = jail.check_writable_dir("newfile.py")
    assert result.parent == tmp_path.resolve()


# ── rel و safe_rel ──────────────────────────────────────────────

def test_rel_returns_relative_path(tmp_path):
    jail = WorkspaceJail(tmp_path)
    p = tmp_path / "src" / "main.py"
    assert jail.rel(p) == "src/main.py"


def test_safe_rel_returns_default_for_outside(tmp_path):
    jail = WorkspaceJail(tmp_path)
    outside = tmp_path.parent / "other.py"
    assert jail.safe_rel(outside, default="?") == "?"


def test_exists_in_workspace(tmp_path):
    jail = WorkspaceJail(tmp_path)
    (tmp_path / "x.py").write_text("x")
    assert jail.exists_in_workspace("x.py") is True
    assert jail.exists_in_workspace("nothere.py") is False
    assert jail.exists_in_workspace("../outside.py") is False
