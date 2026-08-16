from pathlib import Path
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DirectoryTree, RichLog, Input
from textual.containers import Horizontal
from textual.work import work

from .config import Settings
from .core.agent import agent_turn
from .core.tool_registry import ToolRegistry
from .providers.openai_compat import OpenAICompatProvider
from .tools.fs import read_file, read_file_schema

class TermuxCoderApp(App):
    TITLE = "◈ agent"
    CSS = """
    Screen {
        background: #000000;
    }

    Header {
        background: #000000;
        color: #4DB6AC;
    }

    RichLog {
        border: round #4DB6AC;
    }

    Horizontal {
        height: 1fr;
    }

    DirectoryTree {
        width: 35;
    }

    RichLog {
        width: 1fr;
    }

    Input {
        dock: bottom;
    }
    """

    def __init__(self, root: Path):
        super().__init__()
        self.root = root
        self.settings = Settings()
        self.messages = []
        
        self.registry = ToolRegistry()
        self.registry.register(read_file_schema, read_file)
        
        self.provider = OpenAICompatProvider(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
            model=self.settings.model
        )

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            DirectoryTree(str(self.root)),
            RichLog(id="chat", wrap=True, markup=True),
        )
        yield Input(placeholder="اكتب طلبك...", id="prompt")
        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return

        chat = self.query_one("#chat", RichLog)
        chat.write(f"[dim]you[/] ❯ {text}")
        event.input.clear()

        self.messages.append({"role": "user", "content": text})
        self.run_agent()

    @work(exclusive=True, group="agent")
    async def run_agent(self) -> None:
        chat = self.query_one("#chat", RichLog)

        async def emit(event: dict):
            if event["type"] == "token":
                pass
            elif event["type"] == "system":
                self.call_from_thread(chat.write, f"[bold red]System:[/] {event['text']}")
            elif event["type"] == "tool_result":
                self.call_from_thread(chat.write, f"[rgb(77,182,172)]◈ agent[/] ▸ tool:{event['name']}\n{event['text']}")

        try:
            await agent_turn(
                self.provider,
                self.messages,
                self.registry.schemas(),
                self.registry,
                emit
            )
            
            # Print the final assistant message
            last_msg = self.messages[-1]
            if last_msg["role"] == "assistant" and last_msg.get("content"):
                self.call_from_thread(chat.write, f"\n[rgb(77,182,172)]◈ agent[/]\n{last_msg['content']}\n")
                
        except Exception as e:
            self.call_from_thread(chat.write, f"[bold red]Error:[/] {e}")
