#!/usr/bin/env python3
"""Generate a repository-specific threat status report.

Usage:
    python scripts/threat_audit.py --output THREAT_AUDIT.md
    python scripts/threat_audit.py --verify --output THREAT_AUDIT.md

The audit is deliberately evidence-based: it checks repository-relative source
and test paths, records the latest source commit, and can run bounded targeted
pytest commands without invoking a shell.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Threat:
    threat_id: str
    name: str
    sources: tuple[str, ...]
    tests: tuple[str, ...]
    command: tuple[str, ...] = ()
    limitation: str = "—"


THREATS = (
    Threat(
        "T1",
        "Path traversal and symlink escape",
        ("src/termux_coder/security/jail.py",),
        ("tests/test_jail.py",),
        ("tests/test_jail.py",),
        "Write-time filesystem races still require dedicated stress testing.",
    ),
    Threat(
        "T2",
        "SSRF in public page fetching",
        ("src/termux_coder/tools/fetch_page.py",),
        ("tests/test_fetch_page.py",),
        ("tests/test_fetch_page.py",),
        "DNS rebinding and long-lived connection stress are not fully modeled.",
    ),
    Threat(
        "T3",
        "Prompt injection in web content",
        ("src/termux_coder/tools/web_sanitizer.py",),
        ("tests/test_web_p0.py", "tests/test_web_p1.py"),
        ("tests/test_web_p0.py", "tests/test_web_p1.py"),
        "Detection is a signal; untrusted content must still be treated as data.",
    ),
    Threat(
        "T4",
        "Secrets written to audit logs",
        (),
        (),
        (),
        "No central SecretScrubber is implemented yet.",
    ),
    Threat(
        "T5",
        "Patch corruption and incomplete rollback",
        ("src/termux_coder/tools/edit.py", "src/termux_coder/tools/patch.py"),
        ("tests/test_patch.py", "tests/test_patch_plan.py"),
        ("tests/test_patch.py", "tests/test_patch_plan.py"),
        "Patch rollback exists; a separate persistent ConfigManager is not present.",
    ),
    Threat(
        "T6",
        "Authentication secrets at rest",
        (),
        (),
        (),
        "No auth-at-rest encryption feature is part of the current repository.",
    ),
    Threat(
        "T9",
        "YOLO or global auto-approval bypass",
        ("src/termux_coder/security/policy.py",),
        ("tests/test_policy.py",),
        ("tests/test_policy.py",),
        "Negative assurance also needs a static scan for bypass flags and aliases.",
    ),
    Threat(
        "T10",
        "Orphaned or unreachable security code",
        (),
        (),
        (),
        "Requires a dedicated dead-code and reachability audit.",
    ),
    Threat(
        "T11",
        "Recursive sub-agent privilege inheritance",
        (),
        (),
        (),
        "Sub-agent execution is not implemented in the current repository.",
    ),
    Threat(
        "T14",
        "Approval replay or argument tampering",
        ("src/termux_coder/models/contracts.py", "src/termux_coder/core/orchestrator.py"),
        ("tests/test_orchestrator.py", "tests/test_orchestrator_integration.py"),
        ("tests/test_orchestrator.py", "tests/test_orchestrator_integration.py"),
        "The implementation uses call fingerprints; there is no separate ApprovalToken type.",
    ),
    Threat(
        "T15",
        "Network stream interception",
        ("src/termux_coder/tools/fetch_page.py",),
        (),
        (),
        "HTTPS verification is used, but certificate pinning is not implemented.",
    ),
)


def _existing(paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(path for path in paths if (ROOT / path).is_file())


def _latest_commit(paths: tuple[str, ...]) -> str:
    existing = _existing(paths)
    if not existing:
        return "—"
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%h %ad", "--date=short", "--", *existing],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "unavailable"


def _run_targeted_tests(threat: Threat) -> tuple[str, str]:
    if not threat.command:
        return "NOT_RUN", "no targeted test command configured"
    command = [sys.executable, "-m", "pytest", "-q", *threat.command]
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "FAIL", "targeted tests timed out after 60s"
    except OSError as exc:
        return "FAIL", f"could not run targeted tests: {exc}"
    if result.returncode == 0:
        return "PASS", "targeted tests passed"
    tail = (result.stdout + "\n" + result.stderr).strip().splitlines()[-1:]
    return "FAIL", tail[0][:200] if tail else f"pytest exited with {result.returncode}"


def _collect_count() -> str:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    match = re.search(r"(\d+) tests? collected", result.stdout + result.stderr)
    return match.group(1) if match else "unavailable"


def audit(verify: bool) -> tuple[str, dict[str, int]]:
    rows: list[str] = []
    stats = {"IMPLEMENTED": 0, "PARTIAL": 0, "PLANNED": 0}
    rows.append("# Threat Audit — termux-coder")
    rows.append("")
    rows.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}")
    rows.append(f"**Collected tests:** `{_collect_count()}`")
    rows.append("")
    rows.append("> Status is evidence-based and repository-specific. It is not a security certification.")
    rows.append("")
    rows.append("| ID | Threat | Status | Source evidence | Test evidence | Targeted verification | Latest source commit | Known limitation |")
    rows.append("|---|---|---|---|---|---|---|---|")

    for threat in THREATS:
        sources = _existing(threat.sources)
        tests = _existing(threat.tests)
        if sources and tests:
            verification, verification_note = (
                _run_targeted_tests(threat) if verify else ("NOT_RUN", "run with --verify")
            )
            status = "IMPLEMENTED" if verification == "PASS" else "PARTIAL"
        elif sources or tests:
            verification, verification_note = "NOT_APPLICABLE", "incomplete evidence"
            status = "PARTIAL"
        else:
            verification, verification_note = "NOT_APPLICABLE", "no implementation or test evidence"
            status = "PLANNED"
        stats[status] += 1
        source_text = ", ".join(f"`{path}`" for path in sources) or "—"
        test_text = ", ".join(f"`{path}`" for path in tests) or "—"
        limitation = threat.limitation
        if verification_note not in {"targeted tests passed", "incomplete evidence", "no implementation or test evidence"}:
            limitation = f"{limitation} Verification: {verification_note}."
        rows.append(
            f"| {threat.threat_id} | {threat.name} | **{status}** | {source_text} | {test_text} | `{verification}` | `{_latest_commit(threat.sources)}` | {limitation} |"
        )

    rows.extend(
        [
            "",
            "## Summary",
            "",
            f"- IMPLEMENTED: `{stats['IMPLEMENTED']}`",
            f"- PARTIAL: `{stats['PARTIAL']}`",
            f"- PLANNED: `{stats['PLANNED']}`",
            "",
            "## Interpretation",
            "",
            "`IMPLEMENTED` requires source evidence, test evidence, and a passing targeted command when generated with `--verify`. `PARTIAL` means evidence exists but the proof is incomplete or the targeted tests did not pass. `PLANNED` means no repository evidence was found.",
            "",
        ]
    )
    return "\n".join(rows), stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "THREAT_AUDIT.md")
    parser.add_argument("--verify", action="store_true", help="run bounded targeted pytest commands")
    args = parser.parse_args()
    report, stats = audit(args.verify)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.write_text(report, encoding="utf-8")
    print(f"wrote {output}")
    print(f"IMPLEMENTED={stats['IMPLEMENTED']} PARTIAL={stats['PARTIAL']} PLANNED={stats['PLANNED']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
