# Verification Threat Model

## Scope

`VerificationRunner` runs project-defined checks after an approved mutation. Verification is not inherently safe: `pytest`, `unittest`, linters, and compilers can load project code, plugins, configuration files, or subprocesses. The runner therefore treats verification as a bounded execution boundary, not as a trusted read operation.

## Required controls

| Control | Current rule |
|---|---|
| Argument form | The TOML command must be a non-empty argv list; shell command strings are rejected. |
| Program allowlist | Only configured program names are accepted. Shell interpreters are not in the default allowlist. |
| Python restriction | `python` and `python3` must use `-m` with an allowlisted module; `-c` and script-file execution are rejected. |
| Module allowlist | `pytest`, `py_compile`, `compileall`, `unittest`, `ruff`, `mypy`, and `pyright` are allowed modules. |
| Timeout | The effective timeout is bounded by the configured timeout and a hard 30-second ceiling. |
| Output limit | stdout and stderr are read through bounded readers and marked as truncated when necessary. |
| Process cleanup | The process starts in a new session; timeout terminates the process group and escalates to SIGKILL. |
| Repair loop | Verification-driven repair is limited to three attempts by default, then the orchestrator fails closed. |
| Mutation recovery | Failed verification triggers PatchPlan rollback when a plan identifier is available. |
| Approval | The runner exposes `requires_approval=True`; automatic GRANULAR verification is limited to the separate command-policy allowlist. |

## Trust boundary

The verification command is configured inside the workspace, so the configuration itself must be included in the approved patch when modified. A passing verification result proves only that the bounded command exited successfully; it is not proof that the repository is safe or free of malicious test behavior.

```text
approved mutation
    → Safe Preview + fingerprint
    → atomic apply
    → bounded VerificationRunner
    → pass: continue / fail: rollback or bounded repair
```

## Explicit non-goals

The runner does not sandbox Python, pytest plugins, Node.js, or project subprocesses. It does not accept arbitrary shell composition, `python -c`, shell interpreters, or unbounded timeouts. Stronger isolation requires a separate sandbox or container design and must not be implied by a passing test.

## Regression tests

The contract is covered by `tests/test_verification.py`, including shell-string rejection, `python -c` rejection, allowlisted `py_compile` and `compileall`, timeout enforcement, hard timeout rejection, bounded output, process timeout behavior, and the maximum repair-attempt counter.
