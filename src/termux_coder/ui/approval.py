from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ApprovalScreen(ModalScreen[bool]):
    CSS = """
    ApprovalScreen { align: center middle; }
    #dialog {
        width: 90%;
        height: 70%;
        border: round #4DB6AC;
        background: #000;
        padding: 1 2;
    }
    #diff { height: 1fr; overflow-y: auto; color: #4DB6AC; }
    Horizontal { height: 3; align: center middle; }
    Button { margin: 0 2; }
    """

    def __init__(self, title: str, body: str):
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="title")
            yield Static(self._body, id="diff")
            with Horizontal():
                yield Button("Allow", id="allow", variant="success")
                yield Button("Reject", id="reject", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "allow")
