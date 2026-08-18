from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from ..config import Settings
from ..security.audit import AuditLog
from ..security.jail import JailViolation, WorkspaceJail
from ..security.policy import PolicyEngine
from ..security.scrubber import scrub
from ..tools.duckduckgo import DuckDuckGoProvider
from ..tools.official_docs import OfficialDocsProvider
from ..tools.resilient_provider import ResilientWebSearchProvider
from .verification import VerificationRunner


CheckStatus = Literal["ok", "warning", "error", "timeout", "skipped"]


@dataclass(frozen=True)
class CheckResult:
    name: str
    category: str
    status: CheckStatus
    message: str
    details: dict[str, object]
    duration_ms: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DoctorReport:
    schema_version: int
    timestamp: str
    version: str
    checks: tuple[CheckResult, ...]

    @property
    def all_passed(self) -> bool:
        return not any(check.status in {"error", "timeout"} for check in self.checks)

    @property
    def exit_code(self) -> int:
        return 0 if self.all_passed else 1

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "timestamp": self.timestamp,
            "version": self.version,
            "checks": [check.as_dict() for check in self.checks],
            "all_passed": self.all_passed,
            "exit_code": self.exit_code,
        }

    def to_json(self) -> str:
        return json.dumps(scrub(self.as_dict()), ensure_ascii=False, indent=2, sort_keys=True)

    def to_human_readable(self, *, verbose: bool = False) -> str:
        lines = [f"termux-coder doctor (schema {self.schema_version})", ""]
        for check in self.checks:
            label = check.status.upper()
            line = f"[{label:<7}] {check.name}: {check.message}"
            if check.duration_ms:
                line += f" ({check.duration_ms}ms)"
            lines.append(line)
            if verbose and check.details:
                details = scrub(check.details)
                lines.append(f"          details: {json.dumps(details, ensure_ascii=False, sort_keys=True)}")
        lines.extend(
            [
                "",
                f"Result: {'PASS' if self.all_passed else 'FAIL'}",
                f"Checks: {len(self.checks)}",
            ]
        )
        return "\n".join(lines)


class DoctorRunner:
    """Run bounded local diagnostics without mutating the workspace."""

    def __init__(self, settings: Settings, *, version: str = "unknown") -> None:
        self.settings = settings
        self.version = version

    @staticmethod
    def _run_check(
        name: str,
        category: str,
        check: Callable[[], tuple[CheckStatus, str, dict[str, object]]],
    ) -> CheckResult:
        started = time.monotonic()
        try:
            status, message, details = check()
        except Exception as exc:
            status, message, details = "error", "check failed", {"error": scrub(str(exc))}
        duration_ms = int((time.monotonic() - started) * 1000)
        return CheckResult(name, category, status, scrub(message), scrub(details), duration_ms)

    def _python(self) -> tuple[CheckStatus, str, dict[str, object]]:
        version = sys.version_info
        if version < (3, 10):
            return "error", "Python >= 3.10 is required", {"version": sys.version}
        return "ok", f"Python {version.major}.{version.minor}.{version.micro}", {"version": sys.version}

    def _dependencies(self) -> tuple[CheckStatus, str, dict[str, object]]:
        missing: list[str] = []
        for module in ("textual", "openai", "httpx", "bs4"):
            try:
                __import__(module)
            except Exception:
                missing.append(module)
        if missing:
            return "error", "required Python dependencies are missing", {"missing": missing}
        return "ok", "required Python dependencies are available", {
            "checked": ["textual", "openai", "httpx", "bs4"]
        }

    def _binaries(self) -> tuple[CheckStatus, str, dict[str, object]]:
        required = ("git", "grep")
        optional = ("node", "pylsp")
        missing_required = [name for name in required if shutil.which(name) is None]
        missing_optional = [name for name in optional if shutil.which(name) is None]
        if missing_required:
            return "error", "required binaries are missing", {"missing": missing_required}
        if missing_optional:
            return "warning", "required binaries are available; optional tools are missing", {
                "optional_missing": missing_optional
            }
        return "ok", "required and optional binaries are available", {"checked": [*required, *optional]}

    def _policy(self) -> tuple[CheckStatus, str, dict[str, object]]:
        try:
            engine = PolicyEngine(self.settings.security_mode)
            decision = engine.evaluate_tool("read_file")
            if not decision.allowed or decision.requires_approval:
                return "error", "read policy is not automatic", {"mode": self.settings.security_mode}
            return "ok", f"policy mode {self.settings.security_mode}", {"risk": decision.risk}
        except Exception as exc:
            return "error", "policy configuration is invalid", {"error": str(exc)}

    def _workspace(self) -> tuple[CheckStatus, str, dict[str, object]]:
        workspace = self.settings.workspace.resolve()
        if not workspace.is_dir():
            return "error", "workspace directory does not exist", {"workspace": str(workspace)}
        try:
            jail = WorkspaceJail(workspace)
            probe = jail.check(".")
        except (JailViolation, OSError) as exc:
            return "error", "workspace jail initialization failed", {"error": str(exc)}
        status: CheckStatus = "warning" if workspace == Path.home().resolve() else "ok"
        message = "workspace jail is valid"
        if status == "warning":
            message = "workspace is the home directory; use a project directory when possible"
        return status, message, {"workspace": str(probe)}

    def _scrubber(self) -> tuple[CheckStatus, str, dict[str, object]]:
        sample = {"api_key": "doctor-secret", "message": "safe diagnostic"}
        cleaned = scrub(sample)
        if "doctor-secret" in json.dumps(cleaned):
            return "error", "secret scrubber failed its sample check", {}
        return "ok", "secret scrubber redacts sensitive fields", {"sample": cleaned}

    def _audit(self) -> tuple[CheckStatus, str, dict[str, object]]:
        with tempfile.TemporaryDirectory(prefix="termux-coder-doctor-") as directory:
            path = Path(directory) / "audit.jsonl"
            AuditLog(path).log("doctor_check", api_key="doctor-secret")
            content = path.read_text(encoding="utf-8")
            if "doctor-secret" in content:
                return "error", "audit log persistence leaked a secret", {}
        return "ok", "audit log writes scrubbed JSONL", {}

    def _verification(self) -> tuple[CheckStatus, str, dict[str, object]]:
        workspace = self.settings.workspace.resolve()
        runner = VerificationRunner(workspace, self.settings)
        argv, reason = runner._load_argv()
        if argv is None:
            if reason == "no verification config":
                return "skipped", "verification config is not present", {}
            return "error", "verification config is invalid", {"reason": reason}
        return "ok", "verification config is valid and allowlisted; command not executed", {
            "argv": list(argv),
            "timeout_s": runner._configured_timeout_s,
        }

    def _sessions(self) -> tuple[CheckStatus, str, dict[str, object]]:
        try:
            with tempfile.TemporaryDirectory(prefix="termux-coder-doctor-") as directory:
                db = Path(directory) / "sessions.db"
                with sqlite3.connect(db) as connection:
                    journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                    connection.execute("CREATE TABLE IF NOT EXISTS doctor_check(value TEXT)")
                return "ok", "SQLite session storage is writable", {"journal_mode": journal_mode}
        except Exception as exc:
            return "error", "SQLite session storage check failed", {"error": str(exc)}

    def _provider_health(self) -> tuple[CheckStatus, str, dict[str, object]]:
        base = DuckDuckGoProvider(
            timeout_s=self.settings.web_search_timeout_s,
            max_response_bytes=self.settings.web_search_max_response_bytes,
            max_results=self.settings.web_search_max_results,
        )
        provider: object = base
        if self.settings.web_search_provider == "official_docs":
            provider = OfficialDocsProvider(base, allowed_domains=self.settings.official_docs_domains)
        resilient = ResilientWebSearchProvider(
            provider,
            max_retries=self.settings.web_search_max_retries,
            base_delay_s=self.settings.web_search_retry_base_delay_s,
            failure_threshold=self.settings.web_search_circuit_failure_threshold,
            cooldown_s=self.settings.web_search_circuit_cooldown_s,
            cache_ttl_s=self.settings.web_search_cache_ttl_s,
            max_cache_entries=self.settings.web_search_cache_entries,
        )
        return "ok", f"{self.settings.web_search_provider} provider is configured", {
            "health": resilient.health().as_dict(),
            "network_probe": "not run; use a future explicit network flag",
        }

    def run(self) -> DoctorReport:
        checks = (
            ("python", "environment", self._python),
            ("dependencies", "environment", self._dependencies),
            ("binaries", "environment", self._binaries),
            ("policy", "security", self._policy),
            ("workspace", "security", self._workspace),
            ("secret_scrubber", "security", self._scrubber),
            ("audit_log", "security", self._audit),
            ("verification_config", "verification", self._verification),
            ("session_storage", "data", self._sessions),
            ("provider_health", "network", self._provider_health),
        )
        results = tuple(self._run_check(name, category, check) for name, category, check in checks)
        return DoctorReport(
            schema_version=1,
            timestamp=datetime.now(timezone.utc).isoformat(),
            version=self.version,
            checks=results,
        )


def run_doctor(
    settings: Settings,
    *,
    json_output: bool = False,
    verbose: bool = False,
    network: bool = False,
) -> int:
    """Run local diagnostics; network is reserved for the explicit next phase."""
    del network  # P4.4a deliberately performs no live network probes.
    report = DoctorRunner(settings).run()
    print(report.to_json() if json_output else report.to_human_readable(verbose=verbose))
    return report.exit_code


__all__ = ["CheckResult", "DoctorReport", "DoctorRunner", "run_doctor"]
