import asyncio
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

from termux_coder.security.policy import CommandPolicy
from termux_coder.tools.shell import RunCommandArgs, run_command


class RecordingUI:
    def __init__(self):
        self.events = []

    async def on_event(self, kind, **payload):
        self.events.append((kind, payload))

    async def request_approval(self, _kind, _payload):
        return True


class RecordingAudit:
    def __init__(self):
        self.events = []

    def log(self, kind, **payload):
        self.events.append((kind, payload))


def make_context(tmp_path: Path):
    return SimpleNamespace(
        policy=CommandPolicy("AUTO"),
        jail=SimpleNamespace(root=tmp_path),
        settings=SimpleNamespace(command_timeout=10, max_output_chars=8000),
        state=SimpleNamespace(read_files=set()),
        audit=RecordingAudit(),
        ui=RecordingUI(),
    )


def run(coro):
    return asyncio.run(coro)


def test_run_command_scrubs_stdout_stderr_and_echoed_command(tmp_path):
    ctx = make_context(tmp_path)
    stdout_secret = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"
    stderr_secret = "ghp_" + "abcdefghijklmnopqrstuvwxyz123456"
    command = (
        f"{shlex.quote(sys.executable)} -c "
        + shlex.quote(
            "import sys; "
            f"print('api_key={stdout_secret}'); "
            f"print('Authorization: Bearer {stderr_secret}', file=sys.stderr)"
        )
    )

    result = run(run_command(RunCommandArgs(command=command), ctx))

    event_kind, event = ctx.ui.events[-1]
    assert event_kind == "shell_done"
    assert stdout_secret not in result
    assert stderr_secret not in result
    assert stdout_secret not in event["output"]
    assert stderr_secret not in event["output"]
    assert stdout_secret not in event["command"]
    assert stderr_secret not in event["command"]
    assert "[API_SECRET_REDACTED]" in result
    assert "[BEARER_TOKEN_REDACTED]" in result


def test_run_command_preserves_non_secret_diagnostics(tmp_path):
    ctx = make_context(tmp_path)
    command = f"{shlex.quote(sys.executable)} -c " + shlex.quote(
        "import sys; print('normal stdout'); print('normal stderr', file=sys.stderr)"
    )

    result = run(run_command(RunCommandArgs(command=command), ctx))

    assert "normal stdout" in result
    assert "normal stderr" in result
    assert ctx.ui.events[-1][1]["output"] == result
