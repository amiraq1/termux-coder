from __future__ import annotations

import asyncio
import json
from pathlib import Path

SEVERITY = {1: "error", 2: "warning", 3: "info", 4: "hint"}


def encode_message(obj: dict) -> bytes:
    """ترويسة LSP إلزامية: Content-Length ثم \r\n\r\n ثم جسم JSON."""
    body = json.dumps(obj).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def format_diagnostic(d: dict) -> str:
    line = d.get("range", {}).get("start", {}).get("line", 0) + 1
    sev = SEVERITY.get(d.get("severity", 1), "problem")
    code = d.get("code")
    suffix = f" [{code}]" if code is not None else ""
    return f"line {line}: {sev}: {d.get('message', '')}{suffix}"


class LspClient:
    def __init__(self, cmd: list[str], root: Path):
        self.cmd = cmd
        self.root = root
        self.proc = None
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self.diagnostics: dict[str, list[dict]] = {}
        self.alive = False
        self._reader_task = None

    async def start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            *self.cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self.alive = True
        self._reader_task = asyncio.create_task(self._read_loop())
        await self.request(
            "initialize",
            {
                "processId": None,
                "rootUri": self.root.as_uri(),
                "rootPath": str(self.root),
                "capabilities": {},
            },
        )
        await self.notify("initialized", {})

    async def request(self, method: str, params: dict):
        self._id += 1
        rid = self._id
        self.proc.stdin.write(
            encode_message({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        )
        await self.proc.stdin.drain()
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            return await asyncio.wait_for(fut, timeout=10)
        finally:
            self._pending.pop(rid, None)

    async def notify(self, method: str, params: dict) -> None:
        self.proc.stdin.write(
            encode_message({"jsonrpc": "2.0", "method": method, "params": params})
        )
        await self.proc.stdin.drain()

    async def _read_loop(self) -> None:
        if self.proc is None or self.proc.stdout is None:
            raise RuntimeError("LSP process is not ready: proc or stdout is None")
        try:
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                headers = {}
                while line and line.strip():
                    key, _, value = line.decode("ascii", "replace").partition(":")
                    headers[key.strip().lower()] = value.strip()
                    line = await self.proc.stdout.readline()
                length = int(headers.get("content-length", 0))
                if length <= 0:
                    continue
                body = await self.proc.stdout.readexactly(length)
                self._dispatch(json.loads(body))
        except (asyncio.IncompleteReadError, ConnectionResetError, ValueError):
            pass
        finally:
            self.alive = False
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("lsp server died"))
            self._pending.clear()

    def _dispatch(self, msg: dict) -> None:
        if "id" in msg and ("result" in msg or "error" in msg):
            fut = self._pending.get(msg["id"])
            if fut and not fut.done():
                if "error" in msg:
                    fut.set_exception(RuntimeError(msg["error"].get("message", "lsp error")))
                else:
                    fut.set_result(msg["result"])
        elif msg.get("method") == "textDocument/publishDiagnostics":
            params = msg.get("params", {})
            self.diagnostics[params.get("uri", "")] = params.get("diagnostics", [])

    async def did_open(self, path: Path, text: str) -> None:
        await self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": path.as_uri(),
                    "languageId": "python",
                    "version": 0,
                    "text": text,
                }
            },
        )

    async def did_change(self, path: Path, text: str, version: int) -> None:
        await self.notify(
            "textDocument/didChange",
            {
                "textDocument": {"uri": path.as_uri(), "version": version},
                "contentChanges": [{"text": text}],
            },
        )

    async def shutdown(self) -> None:
        if not self.alive:
            return
        try:
            await self.request("shutdown", {})
            await self.notify("exit", {})
        except (OSError, asyncio.TimeoutError, ConnectionResetError):
            pass  # LSP shutdown is best-effort; errors here are non-critical
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
        if self._reader_task:
            self._reader_task.cancel()
