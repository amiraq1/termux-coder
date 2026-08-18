from __future__ import annotations

from .native import AnthropicProvider, GeminiProvider
from .openai_compat import OpenAICompatProvider
from .selection import ProviderSelection


def create_provider(selection: ProviderSelection, model: str):
    """Build the protocol-specific provider while preserving the old contract."""
    if selection.protocol == "anthropic":
        return AnthropicProvider(selection.api_key, selection.base_url, model)
    if selection.protocol == "gemini":
        return GeminiProvider(selection.api_key, selection.base_url, model)
    return OpenAICompatProvider(selection.api_key, selection.base_url, model)
