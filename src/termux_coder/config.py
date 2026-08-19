from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    """يدعم TERMUX_CODER_OPENAI_API_KEY و OPENAI_API_KEY معًا."""
    return os.environ.get(f"TERMUX_CODER_{name}", os.environ.get(name, default))


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = _env(name, ",".join(default))
    return tuple(item.strip().lower().rstrip(".") for item in value.split(",") if item.strip())


SUPPORTED_SECURITY_MODES = frozenset({"ASK", "READONLY", "GRANULAR", "AUTO"})


@dataclass
class Settings:
    workspace: Path = field(default_factory=lambda: Path(_env("WORKSPACE", ".")))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY", "EMPTY"))
    openai_base_url: str = field(
        default_factory=lambda: _env("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )
    # auto selects the first configured provider; explicit names include
    # nvidia, openai, openrouter, groq, and together.
    provider: str = field(default_factory=lambda: _env("PROVIDER", "auto").lower())
    providers_config_path: str = field(default_factory=lambda: _env("PROVIDERS_CONFIG", ""))
    model: str = field(default_factory=lambda: _env("MODEL", "gpt-4o-mini"))

    # ASK | READONLY | GRANULAR | AUTO (AUTO غير افتراضي ولا يُنصح به على الهاتف)
    security_mode: str = field(default_factory=lambda: _env("SECURITY", "ASK"))
    # Show only compact progress indicators; never expose raw model reasoning.
    show_thinking: bool = field(default_factory=lambda: _env("SHOW_THINKING", "0") == "1")
    tui_show_activity: bool = field(default_factory=lambda: _env("TUI_SHOW_ACTIVITY", "1") == "1")
    tui_show_status: bool = field(default_factory=lambda: _env("TUI_SHOW_STATUS", "1") == "1")
    tui_auto_focus: bool = field(default_factory=lambda: _env("TUI_AUTO_FOCUS", "1") == "1")
    # auto follows UTF-8 terminal capabilities; use ascii for legacy fonts.
    tui_unicode: str = field(default_factory=lambda: _env("TUI_UNICODE", "auto").lower())
    tui_model_next_key: str = field(default_factory=lambda: _env("TUI_MODEL_NEXT_KEY", "ctrl+down"))
    tui_model_prev_key: str = field(default_factory=lambda: _env("TUI_MODEL_PREV_KEY", "ctrl+up"))

    command_timeout: int = field(default_factory=lambda: int(_env("COMMAND_TIMEOUT", "120")))
    max_tool_rounds: int = 20
    max_file_chars: int = 30_000
    max_output_chars: int = 12_000
    state_dir_name: str = ".termux_coder"

    web_search_enabled: bool = field(default_factory=lambda: _env("WEB_SEARCH", "1") == "1")
    research_auto_enabled: bool = field(default_factory=lambda: _env("RESEARCH_AUTO", "1") == "1")
    # Adapter layer is enabled by default; set to 0 for the legacy provider path.
    capability_adapters_enabled: bool = field(
        default_factory=lambda: _env("CAPABILITY_ADAPTERS", "1") == "1"
    )
    web_search_provider: str = field(default_factory=lambda: _env("SEARCH_PROVIDER", "duckduckgo").lower())
    official_docs_domains: tuple[str, ...] = field(
        default_factory=lambda: _csv_env(
            "OFFICIAL_DOCS_DOMAINS",
            (
                "docs.python.org",
                "python.org",
                "pydantic.dev",
                "fastapi.tiangolo.com",
                "docs.pytest.org",
                "numpy.org",
                "pandas.pydata.org",
                "nodejs.org",
                "typescriptlang.org",
                "react.dev",
                "nextjs.org",
                "docs.docker.com",
                "kubernetes.io",
                "docs.github.com",
            ),
        )
    )
    web_search_timeout_s: float = field(default_factory=lambda: float(_env("SEARCH_TIMEOUT", "10")))
    web_search_max_response_bytes: int = field(
        default_factory=lambda: int(_env("SEARCH_MAX_RESPONSE_BYTES", "500000"))
    )
    web_search_max_results: int = field(
        default_factory=lambda: int(_env("SEARCH_MAX_RESULTS", "5"))
    )
    web_search_max_retries: int = field(
        default_factory=lambda: int(_env("SEARCH_MAX_RETRIES", "2"))
    )
    web_search_retry_base_delay_s: float = field(
        default_factory=lambda: float(_env("SEARCH_RETRY_BASE_DELAY", "0.25"))
    )
    web_search_circuit_failure_threshold: int = field(
        default_factory=lambda: int(_env("SEARCH_CIRCUIT_FAILURES", "3"))
    )
    web_search_circuit_cooldown_s: float = field(
        default_factory=lambda: float(_env("SEARCH_CIRCUIT_COOLDOWN", "60"))
    )
    web_search_cache_ttl_s: float = field(
        default_factory=lambda: float(_env("SEARCH_CACHE_TTL", "30"))
    )
    web_search_cache_entries: int = field(
        default_factory=lambda: int(_env("SEARCH_CACHE_ENTRIES", "32"))
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
    execution_trace_enabled: bool = field(
        default_factory=lambda: _env("EXECUTION_TRACE", "1") == "1"
    )
    # Professional coding workflow is enabled by default; set to 0 for the
    # legacy general-purpose prompt and behavior.
    software_engineer_mode: bool = field(
        default_factory=lambda: _env("SOFTWARE_ENGINEER", "1") == "1"
    )
    analyzing_enabled: bool = field(
        default_factory=lambda: _env("ANALYZING", "0") == "1"
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

    def __post_init__(self) -> None:
        self.security_mode = self.security_mode.upper()
        if self.security_mode not in SUPPORTED_SECURITY_MODES:
            allowed = ", ".join(sorted(SUPPORTED_SECURITY_MODES))
            raise ValueError(f"unsupported security mode {self.security_mode!r}; choose one of {allowed}")

    @property
    def state_dir(self) -> Path:
        return self.workspace / self.state_dir_name

    @property
    def backup_dir(self) -> Path:
        return self.state_dir / "backups"
