from __future__ import annotations

import pytest

from termux_coder.providers.selection import select_provider


_BASE_URL_NAMES = (
    "NVIDIA_BASE_URL",
    "OPENAI_BASE_URL",
    "OPENROUTER_BASE_URL",
    "GROQ_BASE_URL",
    "TOGETHER_BASE_URL",
    "TERMUX_CODER_NVIDIA_BASE_URL",
    "TERMUX_CODER_OPENAI_BASE_URL",
    "TERMUX_CODER_OPENROUTER_BASE_URL",
    "TERMUX_CODER_GROQ_BASE_URL",
    "TERMUX_CODER_TOGETHER_BASE_URL",
)

_SECRET_NAMES = (
    "NVIDIA_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GROQ_API_KEY",
    "TOGETHER_API_KEY",
    "TERMUX_CODER_NVIDIA_API_KEY",
    "TERMUX_CODER_OPENAI_API_KEY",
    "TERMUX_CODER_OPENROUTER_API_KEY",
    "TERMUX_CODER_GROQ_API_KEY",
    "TERMUX_CODER_TOGETHER_API_KEY",
)


def _clear_keys(monkeypatch):
    for name in (*_SECRET_NAMES, *_BASE_URL_NAMES):
        monkeypatch.delenv(name, raising=False)


def test_auto_prefers_nvidia_before_other_configured_keys(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-secret")

    selected = select_provider("auto")

    assert selected.name == "nvidia"
    assert selected.api_key == "nvidia-secret"
    assert selected.base_url == "https://integrate.api.nvidia.com/v1"


def test_explicit_provider_wins_over_auto_order(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-secret")
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret")
    monkeypatch.setenv("GROQ_BASE_URL", "https://example.test/v1")

    selected = select_provider("groq")

    assert selected.name == "groq"
    assert selected.api_key == "groq-secret"
    assert selected.base_url == "https://example.test/v1"


def test_termux_prefixed_key_overrides_unprefixed_key(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "unprefixed-secret")
    monkeypatch.setenv("TERMUX_CODER_OPENAI_API_KEY", "prefixed-secret")

    selected = select_provider("openai", legacy_base_url="https://legacy.test/v1")

    assert selected.api_key == "prefixed-secret"
    assert selected.base_url == "https://legacy.test/v1"


def test_legacy_openai_settings_remain_supported(monkeypatch):
    _clear_keys(monkeypatch)

    selected = select_provider(
        "auto",
        legacy_api_key="legacy-secret",
        legacy_base_url="https://legacy.test/v1",
    )

    assert selected.name == "openai"
    assert selected.api_key == "legacy-secret"
    assert selected.base_url == "https://legacy.test/v1"


def test_missing_explicit_provider_key_has_safe_error(monkeypatch):
    _clear_keys(monkeypatch)

    with pytest.raises(RuntimeError) as exc_info:
        select_provider("groq")

    message = str(exc_info.value)
    assert "GROQ_API_KEY" in message
    assert "secret" not in message.lower()


def test_auto_without_keys_lists_names_not_values(monkeypatch):
    _clear_keys(monkeypatch)

    with pytest.raises(RuntimeError) as exc_info:
        select_provider("auto")

    message = str(exc_info.value)
    assert "NVIDIA_API_KEY" in message
    assert "OPENAI_API_KEY" in message
    assert "OPENROUTER_API_KEY" in message
    assert "GROQ_API_KEY" in message
    assert "TOGETHER_API_KEY" in message


def test_unknown_provider_is_rejected_before_key_lookup(monkeypatch):
    _clear_keys(monkeypatch)

    with pytest.raises(ValueError, match="unsupported provider"):
        select_provider("unknown-provider")
