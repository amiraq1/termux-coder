from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="termux-coder")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--cli", action="store_true", help="force CLI mode (default: TUI)")
    args = parser.parse_args()

    from .config import Settings

    settings = Settings(workspace=Path(args.workspace))

    if args.cli:
        from .cli import cli_main

        asyncio.run(cli_main(settings))
        return

    try:
        from .cli import build_agent
        from .ui.app import TermuxCoderApp
        from .ui.cli import CliUI

        agent = build_agent(settings, CliUI())
        TermuxCoderApp(agent).run()
    except Exception as exc:
        print(f"TUI unavailable ({exc}); falling back to CLI.", file=sys.stderr)
        from .cli import cli_main

        asyncio.run(cli_main(settings))


if __name__ == "__main__":
    main()
