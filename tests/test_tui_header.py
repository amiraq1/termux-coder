from __future__ import annotations

from termux_coder.ui.app import TermuxCoderApp


def test_header_value_keeps_short_values_unchanged():
    assert TermuxCoderApp._compact_header_value("openrouter", 24) == "openrouter"


def test_header_value_compacts_long_model_names():
    value = "meta-llama/very-long-model-name-with-many-capabilities"
    compact = TermuxCoderApp._compact_header_value(value, 20)
    assert len(compact) == 20
    assert compact.endswith("…")
    assert compact.startswith("meta-llama/very-lon")
