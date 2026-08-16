import pytest

from termux_coder.security.jail import JailViolation, WorkspaceJail


def test_inside_workspace(tmp_path):
    jail = WorkspaceJail(tmp_path)
    (tmp_path / "project").mkdir()
    assert jail.check("project/x.py").is_relative_to(tmp_path)


def test_sibling_prefix_is_blocked(tmp_path):
    # الحالة المطلوبة صراحة: /project مقابل /project2
    (tmp_path / "project").mkdir()
    (tmp_path / "project2").mkdir()
    jail = WorkspaceJail(tmp_path / "project")
    with pytest.raises(JailViolation):
        jail.check(str(tmp_path / "project2" / "evil.py"))


def test_dotdot_is_blocked(tmp_path):
    jail = WorkspaceJail(tmp_path)
    with pytest.raises(JailViolation):
        jail.check("../etc/passwd")


def test_symlink_escape_is_blocked(tmp_path):
    (tmp_path / "ws").mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    link = tmp_path / "ws" / "link.txt"
    link.symlink_to(outside)
    jail = WorkspaceJail(tmp_path / "ws")
    with pytest.raises(JailViolation):
        jail.check("link.txt")
