from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(f"TERMUX_CODER_{name}", default)


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
    max_tool_rounds: int = 8
    max_file_chars: int = 30_000
    max_output_chars: int = 12_000
    state_dir_name: str = ".termux_coder"

    repo_map_enabled: bool = field(default_factory=lambda: _env("REPO_MAP", "1") == "1")
    repo_map_budget: int = field(default_factory=lambda: int(_env("REPO_MAP_BUDGET", "6000")))

    @property
    def state_dir(self) -> Path:
        return self.workspace / self.state_dir_name

    @property
    def backup_dir(self) -> Path:
        return self.state_dir / "backups"
