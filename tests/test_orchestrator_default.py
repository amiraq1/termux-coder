from termux_coder.config import Settings


def clear_orchestrator_env(monkeypatch):
    for name in (
        "TERMUX_CODER_ORCHESTRATOR",
        "ORCHESTRATOR",
        "TERMUX_CODER_LEGACY",
        "LEGACY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_orchestrator_is_enabled_by_default(monkeypatch):
    clear_orchestrator_env(monkeypatch)

    assert Settings().orchestrator_enabled is True


def test_explicit_orchestrator_zero_selects_legacy(monkeypatch):
    clear_orchestrator_env(monkeypatch)
    monkeypatch.setenv("TERMUX_CODER_ORCHESTRATOR", "0")

    assert Settings().orchestrator_enabled is False


def test_legacy_opt_out_overrides_orchestrator_default(monkeypatch):
    clear_orchestrator_env(monkeypatch)
    monkeypatch.setenv("TERMUX_CODER_LEGACY", "1")

    assert Settings().orchestrator_enabled is False


def test_explicit_orchestrator_one_keeps_safe_path(monkeypatch):
    clear_orchestrator_env(monkeypatch)
    monkeypatch.setenv("TERMUX_CODER_ORCHESTRATOR", "1")

    assert Settings().orchestrator_enabled is True
