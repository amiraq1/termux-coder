from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="termux-coder")
    parser.add_argument("command", nargs="?", choices=["run", "doctor"], default="run")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--tui", action="store_true", help="use the Textual UI instead of the default CLI")
    parser.add_argument("--cli", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output for doctor")
    parser.add_argument("--verbose", action="store_true", help="show doctor check details")
    parser.add_argument("--network", action="store_true", help="reserved for doctor network probes")
    args = parser.parse_args()

    from .config import Settings

    settings = Settings(workspace=Path(args.workspace))

    if args.version:
        from . import __version__
        print(f"termux-coder {__version__}")
        return

    if args.command == "doctor":
        from .core.doctor import run_doctor
        raise SystemExit(
            run_doctor(
                settings,
                json_output=args.json_output,
                verbose=args.verbose,
                network=args.network,
            )
        )

    if not args.tui or args.cli:
        from .cli import cli_main

        asyncio.run(cli_main(settings))
        return

    try:
        from .cli import build_agent
        from .core.session import SessionStore
        from .ui.app import TermuxCoderApp
        from .ui.cli import CliUI

        store = SessionStore(settings.state_dir / "sessions.db")
        
        if settings.openai_api_key in ("", "EMPTY") and "openai.com" in settings.openai_base_url:
            print("No API key loaded; the configured provider may reject requests.")
            print("Load your environment file before starting the agent.")

        key = settings.openai_api_key
        masked = (key[:8] + "…") if len(key) > 8 and key.isascii() else "<invalid>"
        print(f"config: base_url={settings.openai_base_url} model={settings.model} key={masked}")

        agent = build_agent(settings, CliUI(), store=store)
        TermuxCoderApp(agent, settings, store).run()
    except RuntimeError as exc:
        sys.exit(exc)
    except Exception as exc:
        print(f"TUI unavailable ({exc}); falling back to CLI.", file=sys.stderr)
        from .cli import cli_main

        asyncio.run(cli_main(settings))


if __name__ == "__main__":
    main()
