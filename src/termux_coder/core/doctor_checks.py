from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Callable, Literal

from ..security.scrubber import scrub


CheckStatus = Literal["ok", "warning", "error", "timeout", "skipped"]
CheckOutcome = tuple[CheckStatus, str, dict[str, object]]
CheckFunction = Callable[[], CheckOutcome]


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
class CheckSpec:
    name: str
    category: str
    check: CheckFunction
    timeout_s: float = 2.0

    def __post_init__(self) -> None:
        if not self.name or not self.category:
            raise ValueError("check name and category are required")
        if self.timeout_s <= 0 or self.timeout_s > 30:
            raise ValueError("check timeout must be greater than 0 and at most 30 seconds")


class DoctorCheckRegistry:
    """Explicit registry that runs each diagnostic with bounded isolation."""

    def __init__(self, specs: tuple[CheckSpec, ...] = ()) -> None:
        self._specs: dict[str, CheckSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: CheckSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"doctor check already registered: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> CheckSpec | None:
        return self._specs.get(name)

    def specs(self) -> tuple[CheckSpec, ...]:
        return tuple(self._specs.values())

    @staticmethod
    def _run_one(spec: CheckSpec) -> CheckResult:
        started = time.monotonic()
        outcome: list[CheckOutcome] = []
        failure: list[BaseException] = []

        def worker() -> None:
            try:
                outcome.append(spec.check())
            except BaseException as exc:  # isolate check failures; never kill Doctor
                failure.append(exc)

        thread = threading.Thread(
            target=worker,
            name=f"termux-coder-doctor-{spec.name}",
            daemon=True,
        )
        thread.start()
        thread.join(spec.timeout_s)
        duration_ms = int((time.monotonic() - started) * 1000)

        if thread.is_alive():
            return CheckResult(
                spec.name,
                spec.category,
                "timeout",
                f"check timed out after {spec.timeout_s:g}s",
                {},
                duration_ms,
            )
        if failure:
            return CheckResult(
                spec.name,
                spec.category,
                "error",
                "check failed",
                {"error": scrub(str(failure[0]))},
                duration_ms,
            )
        if not outcome:
            return CheckResult(
                spec.name,
                spec.category,
                "error",
                "check returned no result",
                {},
                duration_ms,
            )

        status, message, details = outcome[0]
        return CheckResult(
            spec.name,
            spec.category,
            status,
            scrub(message),
            scrub(details),
            duration_ms,
        )

    def run_all(self) -> tuple[CheckResult, ...]:
        return tuple(self._run_one(spec) for spec in self._specs.values())


__all__ = [
    "CheckFunction",
    "CheckOutcome",
    "CheckResult",
    "CheckSpec",
    "CheckStatus",
    "DoctorCheckRegistry",
]
