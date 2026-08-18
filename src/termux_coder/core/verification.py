from __future__ import annotations

import asyncio
import os
import signal
import time
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class VerificationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
    CONFIG_ERROR = "config_error"


@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus
    exit_code: int
    stdout: str
    stderr: str
    command: tuple[str, ...]
    duration_ms: int
    truncated: bool = False
    reason: str = ""


class VerificationRunner:
    """تشغيل تحقق حتمي محدود وآمن بعد التعديلات."""

    DEFAULT_CONFIG = ".termux-coder.toml"
    DEFAULT_ALLOWED_PROGRAMS = frozenset(
        {"python", "python3", "pytest", "ruff", "mypy", "node", "npm", "git", "printf", "sleep"}
    )
    SAFE_PYTHON_MODULES = frozenset(
        {"pytest", "py_compile", "compileall", "unittest", "ruff", "mypy", "pyright"}
    )
    MAX_TIMEOUT_S = 30.0

    def __init__(
        self,
        workspace_root: Path,
        settings=None,
        *,
        config_name: str = DEFAULT_CONFIG,
        allowed_programs: set[str] | None = None,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.settings = settings
        self.config_path = self.workspace_root / config_name
        self.allowed_programs = frozenset(allowed_programs or self.DEFAULT_ALLOWED_PROGRAMS)
        self.repair_attempts = 0
        self._configured_timeout_s: float | None = None

    @property
    def max_repair_attempts(self) -> int:
        return int(getattr(self.settings, "verification_max_repair_attempts", 3))

    def reset_repair_attempts(self) -> None:
        self.repair_attempts = 0

    def can_repair(self) -> bool:
        return self.repair_attempts < self.max_repair_attempts

    def record_repair_attempt(self) -> None:
        self.repair_attempts += 1

    def _load_argv(self) -> tuple[tuple[str, ...] | None, str]:
        if not self.config_path.exists():
            return None, "no verification config"
        try:
            data = tomllib.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            return None, f"invalid verification TOML: {exc}"

        section = data.get("verification")
        if not isinstance(section, dict):
            return None, "missing [verification] section"
        command = section.get("command")
        if not isinstance(command, list) or not command or not all(
            isinstance(part, str) and part for part in command
        ):
            return None, "verification.command must be a non-empty argv list"
        argv = tuple(command)
        program = os.path.basename(argv[0])
        if program not in self.allowed_programs:
            return None, f"verification program is not allowlisted: {program}"
        if program in {"python", "python3"}:
            if len(argv) < 3 or argv[1] != "-m" or argv[2] not in self.SAFE_PYTHON_MODULES:
                return None, "python verification must use an allowlisted -m module"
        timeout = section.get("timeout_s", getattr(self.settings, "verification_timeout_s", 30))
        if not isinstance(timeout, int | float) or timeout <= 0:
            return None, "verification.timeout_s must be positive"
        if float(timeout) > self.MAX_TIMEOUT_S:
            return None, f"verification.timeout_s exceeds hard limit of {self.MAX_TIMEOUT_S:g}s"
        self._configured_timeout_s = float(timeout)
        return argv, ""

    @property
    def requires_approval(self) -> bool:
        """تشغيل اختبارات المشروع قد ينفذ كودًا غير موثوق، لذا يتطلب موافقة."""
        return True

    def command_for_approval(self) -> tuple[str, ...] | None:
        argv, _ = self._load_argv()
        return argv

    async def _read_bounded(self, stream: asyncio.StreamReader, limit: int) -> tuple[str, bool]:
        chunks: list[bytes] = []
        size = 0
        truncated = False
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            if size < limit:
                keep = chunk[: limit - size]
                chunks.append(keep)
                size += len(keep)
                if len(keep) < len(chunk):
                    truncated = True
            else:
                truncated = True
        text = b"".join(chunks).decode("utf-8", errors="replace")
        return text, truncated

    @staticmethod
    def _terminate_group(proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                proc.terminate()
            except ProcessLookupError:
                pass

    async def run(self) -> VerificationResult:
        argv, reason = self._load_argv()
        if argv is None:
            status = VerificationStatus.SKIPPED if reason == "no verification config" else VerificationStatus.CONFIG_ERROR
            return VerificationResult(status, 0 if status == VerificationStatus.SKIPPED else -1, "", reason, (), 0, reason=reason)

        limit = int(getattr(self.settings, "verification_max_output_chars", 5000))
        settings_timeout = float(getattr(self.settings, "verification_timeout_s", self.MAX_TIMEOUT_S))
        timeout = min(
            self._configured_timeout_s if self._configured_timeout_s is not None else settings_timeout,
            settings_timeout,
            self.MAX_TIMEOUT_S,
        )
        if timeout <= 0:
            return VerificationResult(
                VerificationStatus.CONFIG_ERROR,
                -1,
                "",
                "verification timeout must be positive",
                argv,
                0,
                reason="verification timeout must be positive",
            )
        started = time.monotonic()
        proc = None
        stdout_task = None
        stderr_task = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(self.workspace_root),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            stdout_task = asyncio.create_task(self._read_bounded(proc.stdout, limit))
            stderr_task = asyncio.create_task(self._read_bounded(proc.stderr, limit))
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
                timed_out = False
            except asyncio.TimeoutError:
                timed_out = True
                self._terminate_group(proc)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        proc.kill()
                    await proc.wait()

            stdout, stdout_truncated = await stdout_task
            stderr, stderr_truncated = await stderr_task
            duration = int((time.monotonic() - started) * 1000)
            truncated = stdout_truncated or stderr_truncated
            if timed_out:
                return VerificationResult(
                    VerificationStatus.TIMEOUT, -1, stdout, stderr, argv, duration, truncated,
                    reason=f"verification timed out after {timeout}s",
                )
            status = VerificationStatus.PASSED if proc.returncode == 0 else VerificationStatus.FAILED
            return VerificationResult(status, proc.returncode or 0, stdout, stderr, argv, duration, truncated)
        except asyncio.CancelledError:
            if proc is not None:
                self._terminate_group(proc)
            raise
        except OSError as exc:
            duration = int((time.monotonic() - started) * 1000)
            return VerificationResult(VerificationStatus.FAILED, -1, "", str(exc), argv, duration, reason=str(exc))
