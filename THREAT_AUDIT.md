# Threat Audit — termux-coder

**Generated:** 2026-08-20T09:24:43.329127+00:00
**Collected tests:** `460`

> Status is evidence-based and repository-specific. It is not a security certification.

| ID | Threat | Status | Source evidence | Test evidence | Targeted verification | Latest source commit | Known limitation |
|---|---|---|---|---|---|---|---|
| T1 | Path traversal and symlink escape | **IMPLEMENTED** | `src/termux_coder/security/jail.py` | `tests/test_jail.py` | `PASS` | `7b0d43b 2026-08-18` | Write-time filesystem races still require dedicated stress testing. |
| T2 | SSRF in public page fetching | **IMPLEMENTED** | `src/termux_coder/tools/fetch_page.py` | `tests/test_fetch_page.py` | `PASS` | `50640f8 2026-08-18` | DNS rebinding and long-lived connection stress are not fully modeled. |
| T3 | Prompt injection in web content | **IMPLEMENTED** | `src/termux_coder/tools/web_sanitizer.py` | `tests/test_web_p0.py`, `tests/test_web_p1.py` | `PASS` | `666f436 2026-08-18` | Detection is a signal; untrusted content must still be treated as data. |
| T4 | Secrets written to audit logs | **IMPLEMENTED** | `src/termux_coder/security/scrubber.py`, `src/termux_coder/security/audit.py` | `tests/test_scrubber.py` | `PASS` | `74dc3a9 2026-08-18` | Known credential patterns are covered; arbitrary custom secret formats still require review. |
| T5 | Patch corruption and incomplete rollback | **IMPLEMENTED** | `src/termux_coder/tools/edit.py`, `src/termux_coder/tools/patch.py` | `tests/test_patch.py`, `tests/test_patch_plan.py` | `PASS` | `154877e 2026-08-19` | Patch rollback exists; a separate persistent ConfigManager is not present. |
| T6 | Authentication secrets at rest | **PLANNED** | — | — | `NOT_APPLICABLE` | `—` | No auth-at-rest encryption feature is part of the current repository. |
| T9 | YOLO or global auto-approval bypass | **IMPLEMENTED** | `src/termux_coder/security/policy.py` | `tests/test_policy.py` | `PASS` | `09c4bbc 2026-08-19` | Negative assurance also needs a static scan for bypass flags and aliases. |
| T10 | Orphaned or unreachable security code | **PLANNED** | — | — | `NOT_APPLICABLE` | `—` | Requires a dedicated dead-code and reachability audit. |
| T11 | Recursive sub-agent privilege inheritance | **PLANNED** | — | — | `NOT_APPLICABLE` | `—` | Sub-agent execution is not implemented in the current repository. |
| T14 | Approval replay or argument tampering | **IMPLEMENTED** | `src/termux_coder/models/contracts.py`, `src/termux_coder/core/orchestrator.py` | `tests/test_orchestrator.py`, `tests/test_orchestrator_integration.py` | `PASS` | `b878043 2026-08-20` | The implementation uses call fingerprints; there is no separate ApprovalToken type. |
| T15 | Network stream interception | **PARTIAL** | `src/termux_coder/tools/fetch_page.py` | — | `NOT_APPLICABLE` | `50640f8 2026-08-18` | HTTPS verification is used, but certificate pinning is not implemented. |

## Summary

- IMPLEMENTED: `7`
- PARTIAL: `1`
- PLANNED: `3`

## Interpretation

`IMPLEMENTED` requires source evidence, test evidence, and a passing targeted command when generated with `--verify`. `PARTIAL` means evidence exists but the proof is incomplete or the targeted tests did not pass. `PLANNED` means no repository evidence was found.
