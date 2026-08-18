import asyncio

import pytest

from termux_coder.config import Settings
from termux_coder.core.doctor import DoctorRunner
from termux_coder.core.doctor_network import LiveNetworkProbe
from termux_coder.tools.resilient_provider import ProviderHealth
from termux_coder.tools.web_models import SearchResultItem, WebSearchArgs, WebSearchResult
from termux_coder.tools.web_provider import ProviderUnavailable, WebSearchError


class FakeProvider:
    name = "fake"

    def __init__(self, result=None, error=None, delay_s=0):
        self.result = result
        self.error = error
        self.delay_s = delay_s
        self.calls = 0

    async def search(self, args: WebSearchArgs):
        self.calls += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.error:
            raise self.error
        return self.result or WebSearchResult(
            query=args.query,
            provider=self.name,
            results=[],
            total_found=0,
        )


def test_live_probe_success_is_bounded_and_read_only():
    provider = FakeProvider(
        WebSearchResult(
            query="probe",
            provider="fake",
            total_found=1,
            results=[
                SearchResultItem(
                    title="Python docs",
                    url="https://docs.python.org/",
                    snippet="Official documentation",
                )
            ],
        )
    )

    status, message, details = LiveNetworkProbe(provider, timeout_s=0.5).run()

    assert status == "ok"
    assert message == "live network probe succeeded"
    assert details["provider"] == "fake"
    assert provider.calls == 1


def test_live_probe_timeout_is_reported_without_raising():
    provider = FakeProvider(delay_s=0.05)

    status, message, details = LiveNetworkProbe(provider, timeout_s=0.005).run()

    assert status == "timeout"
    assert "timed out" in message
    assert details["provider"] == "fake"


def test_live_probe_scrubs_provider_errors():
    provider = FakeProvider(error=WebSearchError("api_key=probe-secret"))

    status, message, details = LiveNetworkProbe(provider, timeout_s=0.5).run()

    assert status == "error"
    assert message == "live network probe failed"
    assert "probe-secret" not in str(details)


def test_live_probe_handles_open_circuit_as_warning():
    provider = FakeProvider(error=ProviderUnavailable("provider circuit is open"))

    status, message, details = LiveNetworkProbe(provider, timeout_s=0.5).run()

    assert status == "warning"
    assert "unavailable" in message
    assert details["provider"] == "fake"


class FakeResilientProvider(FakeProvider):
    def health(self):
        return ProviderHealth("fake", 0, False, 0.0, 0)

    def configuration(self):
        return {"max_retries": 0}


def test_doctor_network_flag_adds_probe_only_when_enabled(tmp_path, monkeypatch):
    settings = Settings(workspace=tmp_path)
    provider = FakeResilientProvider(
        WebSearchResult(
            query="probe",
            provider="fake",
            total_found=1,
            results=[],
        )
    )

    local_runner = DoctorRunner(settings, network=False)
    monkeypatch.setattr(local_runner, "_build_provider", lambda: provider)
    local_report = local_runner.run()
    assert not any(check.name == "network_probe" for check in local_report.checks)

    network_runner = DoctorRunner(settings, network=True)
    monkeypatch.setattr(network_runner, "_build_provider", lambda: provider)
    network_report = network_runner.run()
    probe = next(check for check in network_report.checks if check.name == "network_probe")
    assert probe.status == "warning"
    assert probe.details["provider"] == "fake"
    assert provider.calls == 1
