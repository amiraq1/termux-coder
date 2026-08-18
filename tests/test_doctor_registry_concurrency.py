from concurrent.futures import ThreadPoolExecutor
import threading
import time

from termux_coder.core.doctor_checks import CheckSpec, DoctorCheckRegistry


def _run_many(registry: DoctorCheckRegistry, count: int = 12):
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(registry.run_all) for _ in range(count)]
        return [future.result(timeout=5) for future in futures]


def test_registry_supports_concurrent_readonly_runs_without_state_leakage():
    calls = 0
    calls_lock = threading.Lock()

    def healthy_check():
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.002)
        return "ok", "healthy", {"source": "concurrent"}

    registry = DoctorCheckRegistry(
        (CheckSpec("healthy", "concurrency", healthy_check, timeout_s=0.5),)
    )

    reports = _run_many(registry)

    assert len(reports) == 12
    assert all(len(report) == 1 for report in reports)
    assert all(report[0].status == "ok" for report in reports)
    assert all(report[0].name == "healthy" for report in reports)
    assert calls == 12
    assert [spec.name for spec in registry.specs()] == ["healthy"]


def test_concurrent_runs_isolate_timeout_and_exception_results():
    def slow_check():
        time.sleep(0.02)
        return "ok", "too slow", {}

    def failing_check():
        raise RuntimeError("isolated failure")

    registry = DoctorCheckRegistry(
        (
            CheckSpec("slow", "concurrency", slow_check, timeout_s=0.005),
            CheckSpec("failing", "concurrency", failing_check, timeout_s=0.5),
            CheckSpec("healthy", "concurrency", lambda: ("ok", "still runs", {}), timeout_s=0.5),
        )
    )

    reports = _run_many(registry, count=10)

    for report in reports:
        assert [result.name for result in report] == ["slow", "failing", "healthy"]
        assert [result.status for result in report] == ["timeout", "error", "ok"]
        assert report[1].details["error"] == "isolated failure"


def test_concurrent_runs_return_independent_details():
    registry = DoctorCheckRegistry(
        (
            CheckSpec(
                "details",
                "concurrency",
                lambda: ("ok", "details", {"items": []}),
                timeout_s=0.5,
            ),
        )
    )

    first, second = _run_many(registry, count=2)
    first[0].details["items"].append("mutated")

    assert second[0].details == {"items": []}
