from __future__ import annotations

from termux_coder.config import Settings
from termux_coder.ui.provider_picker import ModelPickerScreen


def test_model_picker_normalizes_custom_navigation_keys():
    picker = ModelPickerScreen(
        "Provider",
        ("model-a", "model-b"),
        "model-a",
        next_key="  ctrl+n ",
        prev_key="  ctrl+p ",
    )

    assert picker.next_key == "ctrl+n"
    assert picker.prev_key == "ctrl+p"
    assert picker.models == ("model-a", "model-b")


def test_model_picker_falls_back_to_current_model_when_catalog_is_empty():
    picker = ModelPickerScreen("Provider", (), "current-model")

    assert picker.models == ("current-model",)


def test_tui_settings_are_configurable(monkeypatch):
    monkeypatch.setenv("TERMUX_CODER_TUI_SHOW_ACTIVITY", "0")
    monkeypatch.setenv("TERMUX_CODER_TUI_SHOW_STATUS", "0")
    monkeypatch.setenv("TERMUX_CODER_TUI_MODEL_NEXT_KEY", "alt+j")
    monkeypatch.setenv("TERMUX_CODER_TUI_MODEL_PREV_KEY", "alt+k")

    settings = Settings()

    assert settings.tui_show_activity is False
    assert settings.tui_show_status is False
    assert settings.tui_model_next_key == "alt+j"
    assert settings.tui_model_prev_key == "alt+k"
