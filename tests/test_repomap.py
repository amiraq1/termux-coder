from termux_coder.context.repomap import RepoMap
from termux_coder.security.jail import WorkspaceJail


def test_symbols_and_ranking(tmp_path):
    (tmp_path / "a.py").write_text(
        "class Hub:\n    def ping(self):\n        return 1\n\ndef unused():\n    return 2\n"
    )
    (tmp_path / "b.py").write_text("from a import Hub\nHub()\nHub().ping()\n")
    rm = RepoMap(WorkspaceJail(tmp_path), budget_chars=4000)
    text = rm.render_budget()
    assert "class Hub" in text
    assert "def unused" in text
    # الأكثر استشهادًا أولًا
    assert text.index("class Hub") < text.index("def unused")


def test_skip_dirs(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("function nope(){}")
    (tmp_path / "main.py").write_text("def ok():\n    return 1\n")
    rm = RepoMap(WorkspaceJail(tmp_path))
    text = rm.render_budget()
    assert "nope" not in text
    assert "def ok" in text


def test_budget_truncates(tmp_path):
    for i in range(50):
        (tmp_path / f"m{i}.py").write_text(f"def f{i}():\n    return {i}\n")
    rm = RepoMap(WorkspaceJail(tmp_path), budget_chars=200)
    assert len(rm.render_budget()) <= 200


def test_focus(tmp_path):
    (tmp_path / "a.py").write_text("def alpha(): ...\n\ndef beta(): ...\n")
    rm = RepoMap(WorkspaceJail(tmp_path))
    text = rm.render_full(focus="alpha")
    assert "alpha" in text
    assert "beta" not in text


def test_cache_no_rebuild(tmp_path):
    (tmp_path / "a.py").write_text("def x(): ...")
    rm = RepoMap(WorkspaceJail(tmp_path))
    rm.render_budget()
    assert rm.changed
    rm.render_budget()
    assert not rm.changed  # نفس التوقيع → لا إعادة فحص


def test_reports_python_syntax_errors(tmp_path):
    (tmp_path / "main.py").write_text("def greet(name):\nreturn name\n")
    rm = RepoMap(WorkspaceJail(tmp_path))
    rendered = rm.render_full(focus="main.py")
    assert "Diagnostics:" in rendered
    assert "main.py: syntax error" in rendered
    assert rm.last_stats["symbols"] == 0
    assert rm.last_stats["parse_errors"] == 1


def test_valid_python_map_reports_parse_error_count_zero(tmp_path):
    (tmp_path / "main.py").write_text("def greet(name):\n    return name\n")
    rm = RepoMap(WorkspaceJail(tmp_path))
    rendered = rm.render_full(focus="main.py")
    assert "def greet" in rendered
    assert rm.last_stats["parse_errors"] == 0
