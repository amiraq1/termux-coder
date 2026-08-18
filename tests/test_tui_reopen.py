from __future__ import annotations

import asyncio
import json
from pathlib import Path

from termux_coder.cli import build_agent
from termux_coder.config import Settings
from termux_coder.ui.app import TermuxCoderApp
from termux_coder.ui.cli import CliUI
from termux_coder.ui.provider_picker import ModelPickerScreen, ProviderPickerScreen


def test_ctrl_a_reopens_provider_picker_from_prompt(tmp_path, monkeypatch):
    async def scenario() -> None:
        config_dir = tmp_path / ".termux_coder"
        config_dir.mkdir()
        config_path = config_dir / "providers.json"
        config_path.write_text(
            json.dumps(
                {
                    "providers": [
                        {
                            "name": "demo",
                            "label": "Demo Provider",
                            "protocol": "openai",
                            "key_env": "DEMO_API_KEY",
                            "default_base_url": "https://demo.invalid/v1",
                            "models": ["demo-small", "demo-coder"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("TERMUX_CODER_PROVIDER", "demo")
        monkeypatch.setenv("DEMO_API_KEY", "test-only-key")
        monkeypatch.setenv("TERMUX_CODER_PROVIDERS_CONFIG", str(config_path))
        monkeypatch.setenv("TERMUX_CODER_REPO_MAP", "0")
        monkeypatch.setenv("TERMUX_CODER_LSP", "0")
        monkeypatch.setenv("TERMUX_CODER_WEB_SEARCH", "0")
        monkeypatch.setenv("TERMUX_CODER_RESEARCH_AUTO", "0")
        monkeypatch.setenv("TERMUX_CODER_VERIFICATION", "0")

        settings = Settings(workspace=tmp_path)
        app = TermuxCoderApp(build_agent(settings, CliUI()), settings)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+a")
            await pilot.pause()
            assert isinstance(app.screen, ProviderPickerScreen)

            provider_list = app.screen.query_one("#provider-list")
            provider_list.index = 1
            provider_list.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ModelPickerScreen)

            model_list = app.screen.query_one("#model-list")
            model_list.focus()
            await pilot.press("enter")
            await pilot.pause()

            prompt = app.query_one("#prompt")
            prompt.focus()
            await pilot.press("ctrl+a")
            await pilot.pause()
            assert isinstance(app.screen, ProviderPickerScreen)

    asyncio.run(scenario())
