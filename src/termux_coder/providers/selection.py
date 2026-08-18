"""Provider selection for OpenAI-compatible endpoints.

Built-in providers remain available in code. Optional custom providers can be
loaded from a small JSON file, or from YAML when PyYAML is installed. The
configuration contains environment-variable names only; API key values are
never read from the file.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    key_env: str
    base_url_env: str
    default_base_url: str
    label: str = ""
    category: str = "Providers"
    popular: bool = False
    models: tuple[str, ...] = ()
    protocol: str = "openai"


@dataclass(frozen=True)
class ProviderSelection:
    name: str
    api_key: str
    base_url: str
    key_env: str
    protocol: str = "openai"

    @property
    def redacted_label(self) -> str:
        return f"{self.name} ({self.key_env})"


PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "nvidia": ProviderSpec(
        "nvidia", "NVIDIA_API_KEY", "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1",
        "NVIDIA NIM", "Providers", False,
        ("meta/llama-3.1-8b-instruct", "meta/llama-3.1-70b-instruct"), "openai",
    ),
    "openai": ProviderSpec(
        "openai", "OPENAI_API_KEY", "OPENAI_BASE_URL", "https://api.openai.com/v1",
        "OpenAI (ChatGPT Plus/Pro or API key)", "Popular", True,
        ("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"), "openai",
    ),
    "openrouter": ProviderSpec(
        "openrouter", "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1",
        "OpenRouter", "Providers", False, (), "openai",
    ),
    "groq": ProviderSpec(
        "groq", "GROQ_API_KEY", "GROQ_BASE_URL", "https://api.groq.com/openai/v1",
        "Groq", "Popular", True,
        ("llama-3.1-8b-instant", "llama-3.3-70b-versatile"), "openai",
    ),
    "together": ProviderSpec(
        "together", "TOGETHER_API_KEY", "TOGETHER_BASE_URL", "https://api.together.xyz/v1",
        "Together AI", "Providers", False, (), "openai",
    ),
    "anthropic": ProviderSpec(
        "anthropic", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1",
        "Anthropic (API key)", "Popular", True,
        ("claude-sonnet-4-5", "claude-opus-4-5", "claude-haiku-4-5"), "anthropic",
    ),
    "gemini": ProviderSpec(
        "gemini", "GEMINI_API_KEY", "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta",
        "Google Gemini", "Popular", True,
        ("gemini-2.5-flash", "gemini-2.5-pro"), "gemini",
    ),
}

DEFAULT_AUTO_ORDER = (
    "nvidia", "openai", "openrouter", "groq", "together", "anthropic", "gemini"
)
_CONFIG_FILENAMES = ("providers.json", "providers.yaml", "providers.yml")
_ALLOWED_PROVIDER_FIELDS = frozenset(
    {
        "name",
        "label",
        "category",
        "popular",
        "models",
        "key_env",
        "base_url_env",
        "default_base_url",
        "protocol",
    }
)
_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_MAX_CONFIG_BYTES = 128 * 1024


def _value(name: str) -> str:
    return os.environ.get(f"TERMUX_CODER_{name}", os.environ.get(name, "")).strip()


def _key_for(spec: ProviderSpec) -> str:
    return _value(spec.key_env)


def _config_candidates(workspace: str | Path | None) -> tuple[Path, ...]:
    candidates: list[Path] = []
    if workspace:
        root = Path(workspace).expanduser()
        candidates.extend(root / ".termux_coder" / name for name in _CONFIG_FILENAMES)
    candidates.extend(Path.home() / ".termux_coder" / name for name in _CONFIG_FILENAMES)
    return tuple(candidates)


def _resolve_config_path(
    config_path: str | Path | None,
    workspace: str | Path | None,
) -> Path | None:
    if config_path:
        path = Path(config_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"provider config file not found: {path}")
        return path
    for path in _config_candidates(workspace):
        if path.is_file():
            return path
    return None


def _invalid_config(message: str) -> ValueError:
    return ValueError(f"invalid provider config: {message}")


def _validate_env_name(value: Any, field: str, *, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or not _ENV_RE.fullmatch(value):
        raise _invalid_config(f"{field} must be an uppercase environment-variable name")
    if field == "key_env" and not value.endswith("_API_KEY"):
        raise _invalid_config("key_env must end with _API_KEY")
    if field == "base_url_env" and not value.endswith("_BASE_URL"):
        raise _invalid_config("base_url_env must end with _BASE_URL")
    return value


def _validate_base_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or any(ch.isspace() for ch in value):
        raise _invalid_config("default_base_url must be a non-empty URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise _invalid_config("default_base_url must use http or https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise _invalid_config("default_base_url cannot contain credentials, query, or fragment")
    return value.rstrip("/")


def _parse_config(path: Path) -> Mapping[str, Any]:
    try:
        if path.stat().st_size > _MAX_CONFIG_BYTES:
            raise _invalid_config("file is too large")
        raw = path.read_text(encoding="utf-8")
    except ValueError:
        raise
    except (OSError, UnicodeError) as exc:
        raise _invalid_config(f"file cannot be read ({type(exc).__name__})") from exc

    try:
        if path.suffix.lower() in {".yaml", ".yml"}:
            try:
                import yaml  # type: ignore[import-not-found]
            except ImportError as exc:
                raise _invalid_config("YAML requires the optional PyYAML package") from exc
            data = yaml.safe_load(raw)
        else:
            data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _invalid_config("invalid JSON syntax") from exc
    except ValueError:
        raise
    except Exception as exc:
        raise _invalid_config(f"invalid document ({type(exc).__name__})") from exc

    if not isinstance(data, Mapping):
        raise _invalid_config("top level must be an object")
    return data


def load_custom_providers(
    config_path: str | Path | None = None,
    *,
    workspace: str | Path | None = None,
) -> tuple[dict[str, ProviderSpec], tuple[str, ...]]:
    """Load custom provider specs and an optional auto-selection order.

    The file may be JSON, or YAML when PyYAML is installed. It may contain
    only ``providers`` and ``auto_order``. Provider entries contain names and
    environment-variable names, never API key values, shell commands, or
    arbitrary headers. Missing auto order means custom providers are appended
    after the built-in order.
    """
    path = _resolve_config_path(config_path, workspace)
    if path is None:
        return {}, ()

    data = _parse_config(path)
    unknown_top = set(data) - {"providers", "auto_order"}
    if unknown_top:
        raise _invalid_config("unsupported top-level field")

    raw_providers = data.get("providers", [])
    if not isinstance(raw_providers, list):
        raise _invalid_config("providers must be a list")

    custom: dict[str, ProviderSpec] = {}
    for item in raw_providers:
        if not isinstance(item, Mapping):
            raise _invalid_config("each provider must be an object")
        if set(item) - _ALLOWED_PROVIDER_FIELDS:
            raise _invalid_config("provider contains an unsupported field")

        name = item.get("name")
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name.lower()):
            raise _invalid_config("provider name must match [a-z][a-z0-9_-]{0,31}")
        name = name.lower()
        if name in PROVIDER_SPECS or name in custom:
            raise _invalid_config("provider name is duplicated or built-in")

        label = item.get("label", name)
        if not isinstance(label, str) or not label.strip() or len(label) > 100:
            raise _invalid_config("label must be a non-empty string of at most 100 characters")
        category = item.get("category", "Providers")
        protocol = item.get("protocol", "openai")
        if protocol not in {"openai", "anthropic", "gemini"}:
            raise _invalid_config("protocol must be openai, anthropic, or gemini")
        if category not in {"Popular", "Providers"}:
            raise _invalid_config("category must be Popular or Providers")
        popular = item.get("popular", category == "Popular")
        if not isinstance(popular, bool):
            raise _invalid_config("popular must be a boolean")
        raw_models = item.get("models", [])
        if not isinstance(raw_models, list) or not all(
            isinstance(model, str) and model.strip() and len(model) <= 150
            for model in raw_models
        ):
            raise _invalid_config("models must be a list of non-empty strings")
        models = tuple(model.strip() for model in raw_models)

        key_env = _validate_env_name(item.get("key_env"), "key_env")
        base_url_env = _validate_env_name(item.get("base_url_env"), "base_url_env", required=False)
        if not base_url_env:
            base_url_env = f"{name.upper().replace('-', '_')}_BASE_URL"
        default_base_url = _validate_base_url(item.get("default_base_url"))
        custom[name] = ProviderSpec(
            name,
            key_env,
            base_url_env,
            default_base_url,
            label.strip(),
            category,
            popular,
            models,
            protocol,
        )

    raw_order = data.get("auto_order")
    if raw_order is None:
        return custom, ()
    if not isinstance(raw_order, list) or not all(isinstance(name, str) for name in raw_order):
        raise _invalid_config("auto_order must be a list of provider names")

    available = set(PROVIDER_SPECS) | set(custom)
    order = tuple(name.strip().lower() for name in raw_order)
    if len(set(order)) != len(order) or any(name not in available for name in order):
        raise _invalid_config("auto_order contains an unknown or duplicated provider")
    return custom, order


def provider_catalog(
    config_path: str | Path | None = None,
    *,
    workspace: str | Path | None = None,
) -> tuple[dict[str, ProviderSpec], tuple[str, ...]]:
    """Return built-in and custom provider specs for UI/catalog consumers."""
    custom_specs, configured_order = load_custom_providers(
        config_path, workspace=workspace
    )
    specs = {**PROVIDER_SPECS, **custom_specs}
    order = configured_order or (*DEFAULT_AUTO_ORDER, *custom_specs)
    return specs, order


def configured_provider_names(
    specs: Mapping[str, ProviderSpec],
    *,
    legacy_api_key: str = "",
) -> set[str]:
    """Return configured provider names without exposing key values."""
    configured = {name for name, spec in specs.items() if _key_for(spec) not in {"", "EMPTY"}}
    if legacy_api_key.strip() and "openai" in specs and "openai" not in configured:
        configured.add("openai")
    return configured


def select_provider(
    requested: str = "auto",
    *,
    legacy_api_key: str = "",
    legacy_base_url: str = "",
    config_path: str | Path | None = None,
    workspace: str | Path | None = None,
) -> ProviderSelection:
    """Select one configured OpenAI-compatible provider without exposing keys.

    ``requested`` may be ``auto`` or a built-in/custom provider name. Custom
    providers are loaded from ``config_path`` or from the workspace/home
    ``.termux_coder/providers.{json,yaml,yml}`` discovery locations.
    """
    specs, auto_order = provider_catalog(config_path, workspace=workspace)
    requested = (requested or "auto").strip().lower()
    if requested != "auto" and requested not in specs:
        allowed = ", ".join(("auto", *specs))
        raise ValueError(f"unsupported provider {requested!r}; choose one of {allowed}")

    names = (requested,) if requested != "auto" else auto_order
    for name in names:
        spec = specs[name]
        key = _key_for(spec)
        if name == "openai" and not key:
            key = (legacy_api_key or "").strip()
        if not key or key == "EMPTY":
            continue
        base_url = _value(spec.base_url_env)
        if name == "openai" and not base_url:
            base_url = (legacy_base_url or "").strip()
        return ProviderSelection(
            name=name,
            api_key=key,
            base_url=base_url or spec.default_base_url,
            key_env=spec.key_env,
            protocol=spec.protocol,
        )

    if requested != "auto":
        spec = specs[requested]
        raise RuntimeError(
            f"No API key configured for provider {requested!r}; set {spec.key_env} "
            "or choose another provider."
        )
    expected = ", ".join(spec.key_env for spec in specs.values())
    raise RuntimeError(f"No supported API key found; configure one of: {expected}.")
