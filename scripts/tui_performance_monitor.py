#!/usr/bin/env python3
"""Measure TUI model-picker performance and detect regressions."""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from termux_coder.ui.provider_picker import ModelPickerScreen


def catalog(size: int) -> tuple[str, ...]:
    return tuple(f"provider-coder-{index:05d}-stable-context-window-128k" for index in range(size))


async def measure_once(catalog_size: int, moves: int, query_size: int) -> dict[str, float | int]:
    from textual.app import App, ComposeResult

    models = catalog(catalog_size)
    picker = ModelPickerScreen("Performance Provider", models, models[0])

    class Host(App[None]):
        def compose(self) -> ComposeResult:
            yield from ()

    app = Host()
    async with app.run_test(size=(100, 30)) as pilot:
        await app.push_screen(picker)
        await pilot.pause()
        view = picker.query_one("#model-list")
        view.focus()

        started = time.perf_counter()
        for _ in range(moves):
            picker._move_model(1)
        navigation_ms = (time.perf_counter() - started) * 1000

        query = ("x" * query_size) + "provider-coder-000"
        started = time.perf_counter()
        picker._rebuild(query)
        await pilot.pause()
        rebuild_ms = (time.perf_counter() - started) * 1000

    return {
        "catalog_size": catalog_size,
        "moves": moves,
        "query_size": query_size,
        "navigation_ms": round(navigation_ms, 3),
        "rebuild_ms": round(rebuild_ms, 3),
    }


def measure(args: argparse.Namespace) -> dict:
    samples = [
        asyncio.run(measure_once(args.catalog_size, args.moves, args.query_size))
        for _ in range(args.samples)
    ]
    return {
        "schema": 1,
        "commit": args.commit,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "samples": samples,
        "summary": {
            "navigation_ms_median": round(statistics.median(s["navigation_ms"] for s in samples), 3),
            "rebuild_ms_median": round(statistics.median(s["rebuild_ms"] for s in samples), 3),
        },
    }


def compare(report: dict, baseline_path: Path, threshold: float) -> list[str]:
    if not baseline_path.exists():
        return [f"baseline not found: {baseline_path}"]
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for metric in ("navigation_ms_median", "rebuild_ms_median"):
        current = float(report["summary"][metric])
        previous = float(baseline["summary"][metric])
        allowed = previous * (1 + threshold)
        if current > allowed:
            failures.append(
                f"{metric} regressed from {previous:.3f} ms to {current:.3f} ms "
                f"(allowed {allowed:.3f} ms; threshold {threshold:.1%})"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.25)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--catalog-size", type=int, default=2000)
    parser.add_argument("--moves", type=int, default=250)
    parser.add_argument("--query-size", type=int, default=100_000)
    parser.add_argument("--commit", default="unknown")
    args = parser.parse_args()
    if args.samples < 1 or args.catalog_size < 1 or args.moves < 1 or args.query_size < 0:
        parser.error("samples, catalog-size, and moves must be positive; query-size cannot be negative")

    report = measure(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))

    if args.baseline:
        failures = compare(report, args.baseline, args.threshold)
        if failures:
            for failure in failures:
                print(f"PERFORMANCE REGRESSION: {failure}", file=sys.stderr)
            return 1
        print(f"Performance within {args.threshold:.1%} regression budget.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
