from __future__ import annotations

import asyncio

from termux_coder.ui.app import TextualUI


class FakeApp:
    def __init__(self, result):
        self.result = result
        self.called = None

    async def push_screen_wait(self, screen):
        self.called = screen
        return self.result


def test_textual_ui_waits_for_network_approval_result():
    app = FakeApp(True)
    ui = TextualUI(app)

    approved = asyncio.run(
        ui.request_approval(
            "network",
            {
                "title": "Approve automatic research?",
                "query": "latest Python docs",
                "provider": "duckduckgo",
            },
        )
    )

    assert approved is True
    assert app.called is not None
    assert app.called._title == "Approve automatic research?"
    assert "latest Python docs" in app.called._body


def test_textual_ui_returns_rejection_from_approval_screen():
    app = FakeApp(False)
    ui = TextualUI(app)

    approved = asyncio.run(
        ui.request_approval(
            "network",
            {"title": "Approve?", "url": "https://docs.example.com"},
        )
    )

    assert approved is False
