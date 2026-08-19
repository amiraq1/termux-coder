import asyncio
from pathlib import Path
from types import SimpleNamespace

from termux_coder.config import Settings
from termux_coder.ui.app import ChatFeed, TermuxCoderApp, TextualUI



def test_answer_animation_hides_ui_until_answer_is_complete():
    async def scenario():
        workspace = Path("/tmp/termux-coder-answer-animation")
        workspace.mkdir(parents=True, exist_ok=True)
        settings = Settings(workspace=workspace)
        settings.tui_auto_focus = False
        fake_agent = SimpleNamespace(
            settings=settings,
            jail=SimpleNamespace(root=workspace),
            policy=SimpleNamespace(mode=settings.security_mode),
            session_id="answer-animation-test",
        )
        app = TermuxCoderApp(fake_agent, settings=settings)
        ui = TextualUI(app)

        async with app.run_test(size=(80, 24)) as pilot:
            await ui.on_event("turn_start")
            maincol = app.query_one("#maincol")
            animation = app.query_one("#agent-animation")
            assert app.answer_quiet is True
            assert maincol.has_class("-answer-quiet")
            assert animation.has_class("-visible")
            assert "agent" in str(animation.render())
            assert app.query_one("#feed").display is False
            assert app.query_one("#prompt").display is False

            await ui.on_token("answer text")
            await ui.on_event("assistant_done")
            await pilot.pause()

            assert app.answer_quiet is False
            assert not maincol.has_class("-answer-quiet")
            assert not animation.has_class("-visible")
            assert app.query_one("#feed").display is True
            assert app.query_one("#prompt").display is True
            assert len(app.query_one("#feed", ChatFeed).message_records) == 1

    asyncio.run(scenario())
