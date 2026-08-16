import asyncio
import shutil

import pytest

from termux_coder.lsp.client import encode_message, format_diagnostic


def test_encode_message_framing():
    data = encode_message({"id": 1})
    head, _, body = data.partition(b"\r\n\r\n")
    assert head.startswith(b"Content-Length: ")
    assert int(head.split(b": ")[1]) == len(body)


def test_format_diagnostic():
    d = {"range": {"start": {"line": 4}}, "severity": 1, "message": "undefined", "code": "E1"}
    assert format_diagnostic(d) == "line 5: error: undefined [E1]"


@pytest.mark.skipif(shutil.which("pylsp") is None, reason="pylsp not installed")
def test_live_diagnostics(tmp_path):
    (tmp_path / "bad.py").write_text("def f(:\n")

    async def go():
        from termux_coder.lsp.manager import LspManager
        from termux_coder.security.jail import WorkspaceJail

        class NullUI:
            async def on_event(self, *a, **k):
                pass

        mgr = LspManager(WorkspaceJail(tmp_path), NullUI(), wait=1.0)
        path = tmp_path / "bad.py"
        await mgr.notify_change(path, path.read_text())
        problems = []
        for _ in range(10):
            problems = await mgr.diagnostics(path)
            if problems:
                break
        await mgr.shutdown()
        return problems

    assert asyncio.run(go())
