from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent0.agent.loop import AgentLoop
from agent0.config import load_config, resolve_session_dir
from agent0.executors.local import LocalExecutor
from agent0.providers.deepseek import DeepSeekProvider
from agent0.redact import redact_secrets
from agent0.session import Session
from agent0.tools.registry import default_tools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent0")
    parser.add_argument("--task", required=True, help="User task text")
    parser.add_argument("--cwd", default=".", help="Working directory")
    parser.add_argument("--config", default=None, help="Path to agent.toml")
    parser.add_argument(
        "--continue",
        dest="continue_session",
        action="store_true",
        help="Restore the most recent session. Default is a new session.",
    )
    parser.add_argument("--session-dir", default=None, help="Override session directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cwd = Path(args.cwd).resolve()
    config = load_config(Path(args.config) if args.config else None, cwd=cwd)
    if not config.api_key:
        print("DEEPSEEK_API_KEY is not set", file=sys.stderr)
        return 2

    session_dir = Path(args.session_dir) if args.session_dir else resolve_session_dir(config, cwd)
    messages = None
    if args.continue_session:
        try:
            session = Session.open_latest(session_dir)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        messages = session.load_and_repair(api_key=config.api_key)
        for warning in session.warnings:
            print(f"session warning: {warning}", file=sys.stderr)
    else:
        session = Session.create(session_dir)

    def on_delta(delta: object) -> None:
        text = getattr(delta, "text", "")
        if text:
            sys.stdout.write(text)
            sys.stdout.flush()

    def on_event(event_type: str, payload: dict) -> None:
        if event_type == "tool_execution_start":
            name = payload.get("name")
            print(f"\n[{name}]", file=sys.stderr)

    loop = AgentLoop(
        config=config,
        provider=DeepSeekProvider(config),
        executor=LocalExecutor(cwd),
        tools=default_tools(config),
        listeners=[on_event],
        on_delta=on_delta,
        session=session,
        messages=messages,
    )
    try:
        answer = loop.run(args.task)
    except Exception as exc:
        print(redact_secrets(str(exc), config.api_key), file=sys.stderr)
        return 1
    if answer and not answer.endswith("\n"):
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
