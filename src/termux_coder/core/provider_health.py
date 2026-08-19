from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from time import monotonic
from typing import Any

import httpx


class ProviderHealthState(str, Enum):
    UNKNOWN = "unknown"
    CHECKING = "checking"
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    AUTH_ERROR = "auth_error"
    RATE_LIMITED = "rate_limited"


@dataclass
class ProviderHealth:
    state: ProviderHealthState = ProviderHealthState.UNKNOWN
    latency_ms: float | None = None
    error_kind: str | None = None
    checked_at: float | None = None
    consecutive_failures: int = 0

    def mark_checking(self) -> None:
        self.state = ProviderHealthState.CHECKING
        self.error_kind = None

    def mark_online(self, latency_ms: float) -> None:
        self.state = ProviderHealthState.ONLINE
        self.latency_ms = round(latency_ms, 1)
        self.error_kind = None
        self.checked_at = monotonic()
        self.consecutive_failures = 0

    def mark_failure(self, error_kind: str, latency_ms: float) -> None:
        self.error_kind = error_kind
        self.latency_ms = round(latency_ms, 1)
        self.checked_at = monotonic()
        self.consecutive_failures += 1
        self.state = {
            "network": ProviderHealthState.OFFLINE,
            "timeout": ProviderHealthState.OFFLINE,
            "auth": ProviderHealthState.AUTH_ERROR,
            "rate_limited": ProviderHealthState.RATE_LIMITED,
        }.get(error_kind, ProviderHealthState.DEGRADED)


def classify_provider_error(exc: BaseException) -> str:
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout)):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "network"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            return "auth"
        if status == 429:
            return "rate_limited"
        if 500 <= status < 600:
            return "server"
        return "http_error"
    if isinstance(exc, httpx.HTTPError):
        return "http_error"
    status = getattr(exc, "status_code", None)
    if status in {401, 403}:
        return "auth"
    if status == 429:
        return "rate_limited"
    if isinstance(status, int) and 500 <= status < 600:
        return "server"
    return "provider_error"


def health_payload(
    health: ProviderHealth,
    *,
    provider: str,
    model: str,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": model,
        "state": health.state.value,
        "latency_ms": health.latency_ms,
        "error_kind": health.error_kind,
        "consecutive_failures": health.consecutive_failures,
    }
