from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static

from .. import theme
from ..providers.selection import ProviderSpec


class _ProviderRow(ListItem):
    def __init__(self, name: str, text: str, configured: bool) -> None:
        prefix = "✓ " if configured else "  "
        super().__init__(Label(prefix + text))
        self.provider_name = name


class _ModelRow(ListItem):
    def __init__(self, model: str) -> None:
        super().__init__(Label(model))
        self.model_name = model


class ProviderPickerScreen(ModalScreen):
    """Compact provider selector designed for small Termux screens."""

    CSS = f"""
    ProviderPickerScreen {{
        align: center middle;
        background: rgba(0, 0, 0, 0.78);
    }}
    #provider-dialog {{
        width: 90%;
        max-width: 86;
        height: 76%;
        min-height: 18;
        background: #151515;
        border: solid #272727;
        padding: 1 2;
    }}
    #provider-title {{
        height: 1;
        color: {theme.WHITE};
        text-style: bold;
    }}
    #provider-search {{
        height: 3;
        margin: 1 0;
        border: none;
        background: #151515;
    }}
    #provider-list {{
        height: 1fr;
        background: #151515;
        scrollbar-size: 1 1;
    }}
    _ProviderRow {{ height: 1; padding: 0 1; color: {theme.WHITE}; }}
    _ProviderRow.--highlight {{ background: {theme.ORANGE}; color: #161616; }}
    .section-header {{ height: 1; padding: 0 1; color: {theme.LAVENDER}; text-style: bold; }}
    #provider-footer {{ height: 1; color: {theme.DIM}; }}
    """

    def __init__(
        self,
        specs: dict[str, ProviderSpec],
        order: tuple[str, ...],
        configured: set[str],
        current: str = "auto",
    ) -> None:
        super().__init__()
        self.specs = specs
        self.order = order
        self.configured = configured
        self.current = current

    def compose(self) -> ComposeResult:
        with Container(id="provider-dialog"):
            yield Static("Connect a provider", id="provider-title")
            yield Input(placeholder="Search", id="provider-search")
            yield ListView(id="provider-list")
            yield Static("Enter select   Esc close", id="provider-footer")

    def on_mount(self) -> None:
        self._rebuild("")
        self.query_one("#provider-search", Input).focus()

    def _rebuild(self, query: str) -> None:
        query = query.casefold().strip()
        rows: list[tuple[str, str, bool]] = []
        for name in self.order:
            spec = self.specs.get(name)
            if spec is None:
                continue
            label = spec.label or name
            if query and query not in name.casefold() and query not in label.casefold():
                continue
            rows.append((name, label, spec.category == "Popular" or spec.popular))

        popular = [row for row in rows if row[2]]
        providers = [row for row in rows if not row[2]]
        view = self.query_one("#provider-list", ListView)
        view.clear()
        if popular:
            view.mount(ListItem(Label("Popular"), classes="section-header", disabled=True))
            for name, label, _ in popular:
                view.mount(_ProviderRow(name, label, name in self.configured))
        if providers:
            view.mount(ListItem(Label("Providers"), classes="section-header", disabled=True))
            for name, label, _ in providers:
                view.mount(_ProviderRow(name, label, name in self.configured))
        if not popular and not providers:
            view.mount(ListItem(Label("No providers match your search"), disabled=True))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "provider-search":
            self._rebuild(event.value)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, _ProviderRow):
            self.dismiss(event.item.provider_name)

    def key_escape(self) -> None:
        self.dismiss(None)


class ModelPickerScreen(ModalScreen):
    """Model selector shown after a provider is selected."""

    CSS = f"""
    ModelPickerScreen {{
        align: center middle;
        background: rgba(0, 0, 0, 0.78);
    }}
    #model-dialog {{
        width: 90%;
        max-width: 86;
        height: 70%;
        min-height: 16;
        background: #151515;
        border: solid #272727;
        padding: 1 2;
    }}
    #model-title {{ height: 1; color: {theme.WHITE}; text-style: bold; }}
    #model-search {{ height: 3; margin: 1 0; border: none; background: #151515; }}
    #model-list {{ height: 1fr; background: #151515; scrollbar-size: 1 1; }}
    _ModelRow {{ height: 1; padding: 0 1; color: {theme.WHITE}; }}
    _ModelRow.--highlight {{ background: {theme.ORANGE}; color: #161616; }}
    #model-footer {{ height: 1; color: {theme.DIM}; }}
    """

    def __init__(self, provider_label: str, models: tuple[str, ...], current: str) -> None:
        super().__init__()
        self.provider_label = provider_label
        self.models = tuple(dict.fromkeys(models or (current,)))
        self.current = current

    def compose(self) -> ComposeResult:
        with Container(id="model-dialog"):
            yield Static(self.provider_label, id="model-title")
            yield Input(placeholder="Search", id="model-search")
            yield ListView(id="model-list")
            yield Static("Enter select   Esc back", id="model-footer")

    def on_mount(self) -> None:
        self._rebuild("")
        self.query_one("#model-search", Input).focus()

    def _rebuild(self, query: str) -> None:
        query = query.casefold().strip()
        view = self.query_one("#model-list", ListView)
        view.clear()
        matches = [model for model in self.models if not query or query in model.casefold()]
        for model in matches:
            view.mount(_ModelRow(model))
        if not matches:
            view.mount(ListItem(Label("No models match your search"), disabled=True))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "model-search":
            self._rebuild(event.value)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, _ModelRow):
            self.dismiss(event.item.model_name)

    def key_escape(self) -> None:
        self.dismiss(None)
