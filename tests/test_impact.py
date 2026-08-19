from pathlib import Path

import pytest

from termux_coder.core.impact import ImpactAnalyzer


def test_impact_reports_confirmed_and_possible_references(tmp_path: Path):
    (tmp_path / "target.py").write_text(
        "def greet(name):\n    return name\n",
        encoding="utf-8",
    )
    (tmp_path / "caller.py").write_text(
        "from target import greet\n\ndef run():\n    return greet('x')\n",
        encoding="utf-8",
    )
    (tmp_path / "docs.txt").write_text("greet is documented here\n", encoding="utf-8")

    report = ImpactAnalyzer(tmp_path).analyze("target.py", "greet")

    assert report.target == "target.py::greet"
    assert any(ref.path == "caller.py" and ref.symbol == "run" for ref in report.confirmed_callers)
    assert report.confidence in {"medium", "high"}


def test_impact_reports_dynamic_reference_separately(tmp_path: Path):
    (tmp_path / "target.py").write_text("def greet():\n    return 'ok'\n", encoding="utf-8")
    (tmp_path / "plugin.py").write_text(
        "import importlib\nmodule = importlib.import_module('target')\ngetattr(module, 'greet')()\n",
        encoding="utf-8",
    )

    report = ImpactAnalyzer(tmp_path).analyze("target.py", "greet")

    assert report.unknown_dynamic_references
    assert not any(ref.path == "plugin.py" for ref in report.confirmed_callers)
    assert report.confidence == "medium"


def test_impact_rejects_workspace_escape(tmp_path: Path):
    with pytest.raises(ValueError, match="escapes workspace"):
        ImpactAnalyzer(tmp_path).analyze("../outside.py", "greet")



def test_extract_target_requires_explicit_source_path():
    from termux_coder.core.impact import extract_target

    assert extract_target("what is 1+1") is None
    assert extract_target("review function greet in main.py") == ("main.py", "greet")
    assert extract_target("read src/agent.py") == ("src/agent.py", None)
