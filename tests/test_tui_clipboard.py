from __future__ import annotations

from termux_coder.ui import clipboard


def test_copy_text_uses_allowlisted_backend_and_scrubs_secrets(monkeypatch):
    calls = []

    monkeypatch.setattr(clipboard.shutil, "which", lambda _name: "/usr/bin/clipboard")

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
    fake_key = "sk-" + "12345678901234567890"
    result = clipboard.copy_text(f"answer api_key={fake_key}")

    assert result.ok is True
    assert result.backend == "termux-clipboard-set"
    assert result.redacted is True
    assert len(calls) == 1
    assert calls[0][0][0] == ("/usr/bin/clipboard",)
    assert fake_key not in calls[0][1]["input"]
    assert "shell" not in calls[0][1]


def test_copy_text_fails_cleanly_when_no_backend_exists(monkeypatch):
    monkeypatch.setattr(clipboard.shutil, "which", lambda _name: None)
    result = clipboard.copy_text("answer")
    assert result.ok is False
    assert result.backend is None
    assert result.reason == "clipboard command unavailable"
