from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    """يدعم TERMUX_CODER_OPENAI_API_KEY و OPENAI_API_KEY معًا."""
    return os.environ.get(f"TERMUX_CODER_{name}", os.environ.get(name, default))


@dataclass
class Settings:
    workspace: Path = field(default_factory=lambda: Path(_env("WORKSPACE", ".")))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY", "EMPTY"))
    openai_base_url: str = field(
        default_factory=lambda: _env("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )
    model: str = field(default_factory=lambda: _env("MODEL", "gpt-4o-mini"))

    # ASK | READONLY | AUTO  (AUTO غير افتراضي ولا يُنصح به على الهاتف)
    security_mode: str = field(default_factory=lambda: _env("SECURITY", "ASK"))

    command_timeout: int = field(default_factory=lambda: int(_env("COMMAND_TIMEOUT", "120")))
    max_tool_rounds: int = 20
    max_file_chars: int = 30_000
    max_output_chars: int = 12_000
    state_dir_name: str = ".termux_coder"

    web_search_enabled: bool = field(default_factory=lambda: _env("WEB_SEARCH", "1") == "1")
    web_search_provider: str = field(default_factory=lambda: _env("SEARCH_PROVIDER", "duckduckgo"))
    web_search_timeout_s: float = field(default_factory=lambda: float(_env("SEARCH_TIMEOUT", "10")))
    web_search_max_response_bytes: int = field(
        default_factory=lambda: int(_env("SEARCH_MAX_RESPONSE_BYTES", "500000"))
    )
    web_search_max_results: int = field(
        default_factory=lambda: int(_env("SEARCH_MAX_RESULTS", "5"))
    )

    repo_map_enabled: bool = field(default_factory=lambda: _env("REPO_MAP", "1") == "1")
    repo_map_budget: int = field(default_factory=lambda: int(_env("REPO_MAP_BUDGET", "6000")))

    lsp_enabled: bool = field(default_factory=lambda: _env("LSP", "1") == "1")
    lsp_wait: float = field(default_factory=lambda: float(_env("LSP_WAIT", "0.8")))

    # تفعيل مسار Orchestrator تدريجيًا؛ المسار القديم هو الافتراضي الآمن.
    orchestrator_enabled: bool = field(
        default_factory=lambda: _env("ORCHESTRATOR", "0") == "1"
    )
    verification_enabled: bool = field(
        default_factory=lambda: _env("VERIFICATION", "1") == "1"
    )
    verification_timeout_s: float = field(
        default_factory=lambda: float(_env("VERIFICATION_TIMEOUT", "30"))
    )
    verification_max_output_chars: int = field(
        default_factory=lambda: int(_env("VERIFICATION_MAX_OUTPUT", "5000"))
    )
    verification_max_repair_attempts: int = field(
        default_factory=lambda: int(_env("VERIFICATION_MAX_REPAIRS", "3"))
    )

    @property
    def state_dir(self) -> Path:
        return self.workspace / self.state_dir_name

    @property
    def backup_dir(self) -> Path:
        return self.state_dir / "backups"
