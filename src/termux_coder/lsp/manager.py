from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from .client import LspClient, format_diagnostic


class LspManager:
    """إدارة دورة حياة pylsp مع تحلّل تدريجي: لا خادم = لا انهيار."""

    def __init__(self, jail, ui, enabled: bool = True, wait: float = 0.8):
        self.jail = jail
        self.ui = ui
        self.enabled = enabled
        self.wait = wait
        self.client: LspClient | None = None
        self._failed = False
        self._versions: dict[str, int] = {}
        self._opened: set[str] = set()

    async def ensure(self) -> LspClient | None:
        if not self.enabled or self._failed:
            return None
        if self.client and self.client.alive:
            return self.client

        binary = shutil.which("pylsp")
        if not binary:
            self._failed = True
            self.enabled = False
            await self.ui.on_event(
                "lsp_off", reason="pylsp not installed (pip install python-lsp-server)"
            )
            return None

        try:
            client = LspClient([binary], self.jail.root)
            await client.start()
            self.client = client
            await self.ui.on_event("lsp_on", server="pylsp")
            return client
        except Exception:
            self._failed = True
            self.enabled = False
            await self.ui.on_event("lsp_off", reason="server failed to start")
            return None

    async def notify_change(self, path: Path, text: str) -> None:
        client = await self.ensure()
        if not client:
            return
        uri = path.as_uri()
        if uri not in self._opened:
            await client.did_open(path, text)
            self._opened.add(uri)
        else:
            self._versions[uri] = self._versions.get(uri, 0) + 1
            await client.did_change(path, text, self._versions[uri])

    async def diagnostics(self, path: Path) -> list[str]:
        client = await self.ensure()
        if not client:
            return []
        await asyncio.sleep(self.wait)
        raw = client.diagnostics.get(path.as_uri(), [])
        return [format_diagnostic(d) for d in raw]

    async def shutdown(self) -> None:
        if self.client:
            await self.client.shutdown()
