from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def _apply_show_thinking_override(settings, cli_value: bool | None):
    """Apply an explicit CLI value while preserving the environment default."""
    if cli_value is not None:
        settings.show_thinking = cli_value
    return settings


def _apply_software_engineer_override(settings, cli_value: bool | None):
    """Apply an explicit coding-specialization value over the environment default."""
    if cli_value is not None:
        settings.software_engineer_mode = cli_value
    return settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="termux-coder")
    parser.add_argument("command", nargs="?", choices=["run", "doctor", "traces", "replay"], default="run")
    parser.add_argument("--workspace", default=".")
    parser.add_argument(
        "--providers-config",
        default=None,
        help="path to a JSON/YAML custom providers configuration file",
    )
    parser.add_argument("--tui", action="store_true", help="use the Textual UI instead of the default CLI")
    parser.add_argument("--cli", action="store_true", help=argparse.SUPPRESS)
    thinking_group = parser.add_mutually_exclusive_group()
    thinking_group.add_argument(
        "--show-thinking",
        dest="show_thinking",
        action="store_true",
        default=None,
        help="show compact progress indicators and the loading spinner",
    )
    thinking_group.add_argument(
        "--hide-thinking",
        dest="show_thinking",
        action="store_false",
        help="hide progress indicators and the loading spinner (default)",
    )
    engineering_group = parser.add_mutually_exclusive_group()
    engineering_group.add_argument(
        "--software-engineer",
        dest="software_engineer",
        action="store_true",
        default=None,
        help="use the professional software-engineering workflow",
    )
    engineering_group.add_argument(
        "--general",
        dest="software_engineer",
        action="store_false",
        help="use the general-purpose workflow",
    )
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output for doctor")
    parser.add_argument("--verbose", action="store_true", help="show doctor check details")
    parser.add_argument("--network", action="store_true", help="reserved for doctor network probes")
    parser.add_argument("--trace-id", default=None, help="trace identifier for replay")
    parser.add_argument("--from-step", type=int, default=1, help="first trace step to replay")
    args = parser.parse_args()

    from .config import Settings

    settings = Settings(workspace=Path(args.workspace))
    if args.providers_config is not None:
        settings.providers_config_path = args.providers_config
    _apply_show_thinking_override(settings, args.show_thinking)
    _apply_software_engineer_override(settings, args.software_engineer)

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

    if args.command == "traces":
        import json
        from .core.trace import TraceStore

        rows = TraceStore(settings.state_dir / "traces.jsonl").list_traces()
        if args.json_output:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for row in rows:
                print(
                    f"{row['trace_id']}  {row.get('state') or 'running'}  "
                    f"rounds={row.get('rounds', 0)}  {row.get('started_at') or ''}"
                )
        return

    if args.command == "replay":
        if not args.trace_id:
            parser.error("replay requires --trace-id")
        import json
        from .cli import build_registry
        from .core.agent import Agent
        from .core.replay import ReplayRunner
        from .core.trace import TraceStore
        from .ui.cli import CliUI

        agent = Agent(settings, None, build_registry(), CliUI())

        async def _run_replay():
            try:
                runner = ReplayRunner(
                    TraceStore(settings.state_dir / "traces.jsonl"),
                    agent.registry,
                    agent.ctx,
                )
                items = await runner.run(args.trace_id, from_step=args.from_step)
                payload = [item.__dict__ for item in items]
                if args.json_output:
                    print(json.dumps(payload, ensure_ascii=False, indent=2))
                else:
                    for item in items:
                        detail = item.reason or f"{item.duration_ms}ms"
                        print(f"step {item.step}: {item.tool} [{item.status}] {detail}")
            finally:
                await agent.close()

        asyncio.run(_run_replay())
        return

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
        
        from .providers.selection import select_provider

        selected = select_provider(
            settings.provider,
            legacy_api_key=settings.openai_api_key,
            legacy_base_url=settings.openai_base_url,
            config_path=settings.providers_config_path or None,
            workspace=settings.workspace,
        )
        print(
            f"config: provider={selected.name} key_env={selected.key_env} "
            f"model={settings.model}"
        )

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
