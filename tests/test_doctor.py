import json
import re

from termux_coder.config import Settings
from termux_coder.core.doctor import DoctorRunner, run_doctor


ARABIC = re.compile(r"[\u0600-\u06ff]")


def make_settings(tmp_path):
    return Settings(workspace=tmp_path, openai_api_key="EMPTY")


def test_doctor_report_json_is_valid_and_english_only(tmp_path, capsys):
    code = run_doctor(make_settings(tmp_path), json_output=True)
    output = capsys.readouterr().out
    report = json.loads(output)

    assert code == 0
    assert report["schema_version"] == 1
    assert report["all_passed"] is True
    assert report["exit_code"] == 0
    assert report["checks"]
    assert not ARABIC.search(output)


def test_doctor_human_output_supports_verbose_details(tmp_path, capsys):
    code = run_doctor(make_settings(tmp_path), verbose=True)
    output = capsys.readouterr().out

    assert code == 0
    assert "termux-coder doctor" in output
    assert "Result: PASS" in output
    assert "details:" in output
    assert not ARABIC.search(output)


def test_doctor_isolates_a_failed_check(tmp_path):
    runner = DoctorRunner(make_settings(tmp_path))
    runner._binaries = lambda: (_ for _ in ()).throw(RuntimeError("secret doctor failure"))

    report = runner.run()

    binaries = next(check for check in report.checks if check.name == "binaries")
    python = next(check for check in report.checks if check.name == "python")
    assert binaries.status == "error"
    assert binaries.details["error"] == "secret doctor failure"
    assert python.status == "ok"
    assert report.exit_code == 1


def test_warning_only_doctor_result_is_success(tmp_path):
    runner = DoctorRunner(make_settings(tmp_path))
    runner._binaries = lambda: ("warning", "optional tools are missing", {"optional_missing": ["node"]})

    report = runner.run()

    assert report.all_passed is True
    assert report.exit_code == 0


def test_doctor_scrubs_sensitive_details(tmp_path):
    runner = DoctorRunner(make_settings(tmp_path))
    runner._python = lambda: ("error", "failed", {"api_key": "doctor-secret"})

    report = runner.run()
    serialized = report.to_json()

    assert "doctor-secret" not in serialized
    assert "[REDACTED]" in serialized
