"""Provider selection for OpenAI-compatible endpoints.

Selection is based on explicit provider-specific environment variables, not on
secret prefixes. This avoids guessing from opaque key material and keeps
provider routing deterministic.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    key_env: str
    base_url_env: str
    default_base_url: str


@dataclass(frozen=True)
class ProviderSelection:
    name: str
    api_key: str
    base_url: str
    key_env: str

    @property
    def redacted_label(self) -> str:
        return f"{self.name} ({self.key_env})"


PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "nvidia": ProviderSpec(
        "nvidia", "NVIDIA_API_KEY", "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
    ),
    "openai": ProviderSpec(
        "openai", "OPENAI_API_KEY", "OPENAI_BASE_URL", "https://api.openai.com/v1"
    ),
    "openrouter": ProviderSpec(
        "openrouter", "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    ),
    "groq": ProviderSpec(
        "groq", "GROQ_API_KEY", "GROQ_BASE_URL", "https://api.groq.com/openai/v1"
    ),
    "together": ProviderSpec(
        "together", "TOGETHER_API_KEY", "TOGETHER_BASE_URL", "https://api.together.xyz/v1"
    ),
}

DEFAULT_AUTO_ORDER = ("nvidia", "openai", "openrouter", "groq", "together")


def _value(name: str) -> str:
    return os.environ.get(f"TERMUX_CODER_{name}", os.environ.get(name, "")).strip()


def _key_for(spec: ProviderSpec) -> str:
    return _value(spec.key_env)


def select_provider(
    requested: str = "auto",
    *,
    legacy_api_key: str = "",
    legacy_base_url: str = "",
) -> ProviderSelection:
    """Select one configured OpenAI-compatible provider without exposing keys.

    ``requested`` may be ``auto`` or a provider name. In auto mode the first
    configured provider in DEFAULT_AUTO_ORDER wins. The legacy OPENAI_API_KEY
    and OPENAI_BASE_URL values remain supported as the OpenAI candidate.
    """
    requested = (requested or "auto").strip().lower()
    if requested != "auto" and requested not in PROVIDER_SPECS:
        allowed = ", ".join(("auto", *PROVIDER_SPECS))
        raise ValueError(f"unsupported provider {requested!r}; choose one of {allowed}")

    names = (requested,) if requested != "auto" else DEFAULT_AUTO_ORDER
    for name in names:
        spec = PROVIDER_SPECS[name]
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
        )

    if requested != "auto":
        spec = PROVIDER_SPECS[requested]
        raise RuntimeError(
            f"No API key configured for provider {requested!r}; set {spec.key_env} "
            "or choose another provider."
        )
    expected = ", ".join(spec.key_env for spec in PROVIDER_SPECS.values())
    raise RuntimeError(f"No supported API key found; configure one of: {expected}.")
