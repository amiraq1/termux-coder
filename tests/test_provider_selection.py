from __future__ import annotations

import pytest

from termux_coder.providers.selection import select_provider


_BASE_URL_NAMES = (
    "NVIDIA_BASE_URL",
    "OPENAI_BASE_URL",
    "OPENROUTER_BASE_URL",
    "GROQ_BASE_URL",
    "TOGETHER_BASE_URL",
    "ANTHROPIC_BASE_URL",
    "GEMINI_BASE_URL",
    "TERMUX_CODER_NVIDIA_BASE_URL",
    "TERMUX_CODER_OPENAI_BASE_URL",
    "TERMUX_CODER_OPENROUTER_BASE_URL",
    "TERMUX_CODER_GROQ_BASE_URL",
    "TERMUX_CODER_TOGETHER_BASE_URL",
    "TERMUX_CODER_ANTHROPIC_BASE_URL",
    "TERMUX_CODER_GEMINI_BASE_URL",
)

_SECRET_NAMES = (
    "NVIDIA_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GROQ_API_KEY",
    "TOGETHER_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "TERMUX_CODER_NVIDIA_API_KEY",
    "TERMUX_CODER_OPENAI_API_KEY",
    "TERMUX_CODER_OPENROUTER_API_KEY",
    "TERMUX_CODER_GROQ_API_KEY",
    "TERMUX_CODER_TOGETHER_API_KEY",
    "TERMUX_CODER_ANTHROPIC_API_KEY",
    "TERMUX_CODER_GEMINI_API_KEY",
)


@pytest.fixture(autouse=True)
def _isolate_home(monkeypatch, tmp_path):
    """Redirect HOME so that ~/.termux_coder/providers.json on the real
    filesystem never leaks into the auto-discovery path during tests."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TERMUX_CODER_PROVIDERS_CONFIG", raising=False)
    monkeypatch.delenv("PROVIDERS_CONFIG", raising=False)


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


def test_custom_json_provider_is_loaded_and_selected(tmp_path, monkeypatch):
    _clear_keys(monkeypatch)
    config = tmp_path / "providers.json"
    config.write_text(
        '{"providers": [{"name": "myprovider", '
        '"key_env": "MYPROVIDER_API_KEY", '
        '"base_url_env": "MYPROVIDER_BASE_URL", '
        '"default_base_url": "https://custom.example/v1"}], '
        '"auto_order": ["myprovider", "openai"]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("MYPROVIDER_API_KEY", "custom-secret")

    selected = select_provider("auto", config_path=config)

    assert selected.name == "myprovider"
    assert selected.api_key == "custom-secret"
    assert selected.base_url == "https://custom.example/v1"
    assert selected.key_env == "MYPROVIDER_API_KEY"


def test_custom_provider_uses_termux_prefixed_environment_values(tmp_path, monkeypatch):
    _clear_keys(monkeypatch)
    config = tmp_path / "providers.json"
    config.write_text(
        '{"providers": [{"name": "edge", "key_env": "EDGE_API_KEY", '
        '"base_url_env": "EDGE_BASE_URL", '
        '"default_base_url": "https://default.example/v1"}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("TERMUX_CODER_EDGE_API_KEY", "prefixed-secret")
    monkeypatch.setenv("TERMUX_CODER_EDGE_BASE_URL", "https://override.example/v1")

    selected = select_provider("edge", config_path=config)

    assert selected.api_key == "prefixed-secret"
    assert selected.base_url == "https://override.example/v1"


def test_custom_provider_is_discovered_from_workspace(tmp_path, monkeypatch):
    _clear_keys(monkeypatch)
    config_dir = tmp_path / ".termux_coder"
    config_dir.mkdir()
    (config_dir / "providers.json").write_text(
        '{"providers": [{"name": "local", "key_env": "LOCAL_API_KEY", '
        '"default_base_url": "https://local.example/v1"}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCAL_API_KEY", "local-secret")

    selected = select_provider("local", workspace=tmp_path)

    assert selected.name == "local"
    assert selected.base_url == "https://local.example/v1"


def test_custom_provider_config_rejects_shell_and_secret_fields(tmp_path):
    config = tmp_path / "providers.json"
    config.write_text(
        '{"providers": [{"name": "unsafe", "key_env": "UNSAFE_API_KEY", '
        '"default_base_url": "https://example.test/v1", '
        '"shell": "curl | sh", "api_key": "secret-value"}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported field"):
        select_provider("auto", config_path=config)


def test_custom_provider_config_rejects_credentials_in_base_url(tmp_path):
    config = tmp_path / "providers.json"
    config.write_text(
        '{"providers": [{"name": "unsafe", "key_env": "UNSAFE_API_KEY", '
        '"default_base_url": "https://user:pass@example.test/v1"}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="credentials"):
        select_provider("auto", config_path=config)


def test_invalid_json_has_safe_error(tmp_path):
    config = tmp_path / "providers.json"
    config.write_text('{"providers": [', encoding="utf-8")

    with pytest.raises(ValueError, match="invalid JSON syntax") as exc_info:
        select_provider("auto", config_path=config)

    assert "providers" not in str(exc_info.value).lower()


def test_yaml_requires_optional_dependency_or_loads(tmp_path, monkeypatch):
    _clear_keys(monkeypatch)
    config = tmp_path / "providers.yaml"
    config.write_text(
        "providers:\n"
        "  - name: yamlprovider\n"
        "    key_env: YAMLPROVIDER_API_KEY\n"
        "    default_base_url: https://yaml.example/v1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("YAMLPROVIDER_API_KEY", "yaml-secret")

    try:
        selected = select_provider("yamlprovider", config_path=config)
    except ValueError as exc:
        assert "PyYAML" in str(exc)
    else:
        assert selected.name == "yamlprovider"
        assert selected.base_url == "https://yaml.example/v1"


def test_custom_catalog_metadata_is_loaded(tmp_path):
    config = tmp_path / "providers.json"
    config.write_text(
        '{"providers": [{"name": "edge", "label": "Edge Cloud", '
        '"category": "Popular", "popular": true, '
        '"models": ["edge-small", "edge-large"], '
        '"key_env": "EDGE_API_KEY", '
        '"default_base_url": "https://edge.example/v1"}]}',
        encoding="utf-8",
    )

    from termux_coder.providers.selection import provider_catalog

    specs, order = provider_catalog(config_path=config)

    assert order[-1] == "edge"
    assert specs["edge"].label == "Edge Cloud"
    assert specs["edge"].category == "Popular"
    assert specs["edge"].models == ("edge-small", "edge-large")


def test_custom_catalog_rejects_invalid_models(tmp_path):
    config = tmp_path / "providers.json"
    config.write_text(
        '{"providers": [{"name": "edge", "key_env": "EDGE_API_KEY", '
        '"default_base_url": "https://edge.example/v1", '
        '"models": ["ok", 42]}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="models"):
        select_provider("auto", config_path=config)


def test_custom_protocol_is_preserved_in_selection(tmp_path, monkeypatch):
    _clear_keys(monkeypatch)
    config = tmp_path / "providers.json"
    config.write_text(
        '{"providers": [{"name": "claude_gateway", "protocol": "anthropic", '
        '"key_env": "CLAUDE_GATEWAY_API_KEY", '
        '"default_base_url": "https://gateway.example/v1"}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_GATEWAY_API_KEY", "claude-secret")

    selected = select_provider("claude_gateway", config_path=config)

    assert selected.protocol == "anthropic"
    assert selected.base_url == "https://gateway.example/v1"


def test_custom_protocol_rejects_unknown_value(tmp_path):
    config = tmp_path / "providers.json"
    config.write_text(
        '{"providers": [{"name": "other", "protocol": "unknown", '
        '"key_env": "OTHER_API_KEY", '
        '"default_base_url": "https://other.example/v1"}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="protocol"):
        select_provider("auto", config_path=config)
