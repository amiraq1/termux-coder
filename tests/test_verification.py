from __future__ import annotations

import asyncio
import sys

from termux_coder.core.verification import VerificationRunner, VerificationStatus


def run(coro):
    return asyncio.run(coro)


def test_missing_config_is_skipped(tmp_path):
    result = run(VerificationRunner(tmp_path).run())
    assert result.status == VerificationStatus.SKIPPED
    assert result.command == ()


def test_invalid_toml_is_config_error(tmp_path):
    (tmp_path / ".termux-coder.toml").write_text("[verification\n", encoding="utf-8")
    result = run(VerificationRunner(tmp_path).run())
    assert result.status == VerificationStatus.CONFIG_ERROR


def test_shell_command_form_is_rejected(tmp_path):
    (tmp_path / ".termux-coder.toml").write_text(
        '[verification]\ncommand = "python -c \'print(1)\'"\n', encoding="utf-8"
    )
    result = run(VerificationRunner(tmp_path).run())
    assert result.status == VerificationStatus.CONFIG_ERROR


def test_allowlisted_argv_passes(tmp_path):
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / ".termux-coder.toml").write_text(
        '[verification]\ncommand = ["python", "-m", "py_compile", "main.py"]\n', encoding="utf-8"
    )
    result = run(VerificationRunner(tmp_path).run())
    assert result.status == VerificationStatus.PASSED
    assert result.exit_code == 0


def test_non_allowlisted_program_is_rejected(tmp_path):
    (tmp_path / ".termux-coder.toml").write_text(
        '[verification]\ncommand = ["sh", "-c", "echo unsafe"]\n', encoding="utf-8"
    )
    result = run(VerificationRunner(tmp_path).run())
    assert result.status == VerificationStatus.CONFIG_ERROR
    assert "allowlisted" in result.reason


def test_timeout_returns_and_does_not_raise(tmp_path):
    (tmp_path / ".termux-coder.toml").write_text(
        '[verification]\ncommand = ["sleep", "5"]\n', encoding="utf-8"
    )
    class Settings:
        verification_timeout_s = 0.05
        verification_max_output_chars = 100
    result = run(VerificationRunner(tmp_path, Settings()).run())
    assert result.status == VerificationStatus.TIMEOUT


def test_output_is_bounded(tmp_path):
    (tmp_path / ".termux-coder.toml").write_text(
        '[verification]\ncommand = ["printf", "%s", "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"]\n', encoding="utf-8"
    )
    class Settings:
        verification_timeout_s = 5
        verification_max_output_chars = 32
    result = run(VerificationRunner(tmp_path, Settings()).run())
    assert result.status == VerificationStatus.PASSED
    assert len(result.stdout) <= 32
    assert result.truncated is True
