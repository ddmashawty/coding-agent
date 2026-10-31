from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent0.agent.loop import EVENT_AGENT_END, AgentLoop
from agent0.config import Config, load_config, resolve_session_dir
from agent0.executors.base import Executor
from agent0.executors.local import LocalExecutor
from agent0.providers.base import Provider, StreamDelta
from agent0.providers.deepseek import DeepSeekProvider
from agent0.redact import redact_secrets
from agent0.session import Session
from agent0.telemetry import (
    OUTCOME_ERROR,
    OUTCOME_MAX_STEPS,
    OUTCOME_SUBMITTED,
    EventLog,
    compute_telemetry,
    load_events,
    start_payload_for,
    write_telemetry,
)
from agent0.tools.registry import default_tools, headless_tools
from agent0.workspace import StartupError, prepare_workspace, write_patch

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_STARTUP = 2
EXIT_MAX_STEPS = 3
EXIT_NO_SUBMIT = 4


def parse_interactive(argv: list[str]) -> argparse.Namespace:
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
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow a dirty working tree. Default requires a clean git workspace.",
    )
    return parser.parse_args(argv)


def parse_run(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agent0 run")
    parser.add_argument("--task", required=True, help="User task text")
    parser.add_argument("--cwd", default=".", help="Working directory")
    parser.add_argument("--out", required=True, help="Output directory for session, events, telemetry, patch")
    parser.add_argument("--config", default=None, help="Path to agent.toml")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow a dirty working tree. Default requires a clean git workspace.",
    )
    parser.add_argument(
        "--no-rebuild",
        action="store_true",
        help="Disable context rebuild (M4). Parsed in M3, unused.",
    )
    return parser.parse_args(argv)


def _print_delta(delta: StreamDelta) -> None:
    if delta.text:
        sys.stdout.write(delta.text)
        sys.stdout.flush()


def _print_tool(event_type: str, payload: dict[str, Any]) -> None:
    if event_type == "tool_execution_start":
        name = payload.get("name")
        print(f"\n[{name}]", file=sys.stderr)


def _exit_for(outcome: str, *, headless: bool) -> int:
    if outcome == OUTCOME_ERROR:
        return EXIT_ERROR
    if outcome == OUTCOME_MAX_STEPS:
        return EXIT_MAX_STEPS
    if headless:
        if outcome == OUTCOME_SUBMITTED:
            return EXIT_OK
        return EXIT_NO_SUBMIT
    return EXIT_OK


def _open_session(
    session_dir: Path,
    *,
    continue_session: bool,
    api_key: str,
) -> tuple[Session, list | None]:
    messages = None
    if continue_session:
        try:
            session = Session.open_latest(session_dir)
        except FileNotFoundError as exc:
            raise StartupError(str(exc)) from exc
        messages = session.load_and_repair(api_key=api_key)
        for warning in session.warnings:
            print(f"session warning: {warning}", file=sys.stderr)
    else:
        session = Session.create(session_dir)
    return session, messages


def execute(
    *,
    config: Config,
    cwd: Path,  # host path; tools use executor, not this
    task: str,
    session: Session,
    events_path: Path,
    telemetry_path: Path,
    provider: Provider,
    tools,
    start_commit: str,
    headless: bool,
    executor: Executor,
    patch_path: Path | None = None,
    messages=None,
    extra_listeners: list[Callable[[str, dict[str, Any]], None]] | None = None,
    on_delta: Callable[[StreamDelta], None] | None = None,
) -> int:
    event_log = EventLog(events_path)
    listeners = [event_log, *(extra_listeners or [])]
    loop = AgentLoop(
        config=config,
        provider=provider,
        executor=executor,
        tools=tools,
        listeners=listeners,
        on_delta=on_delta,
        session=session,
        messages=messages,
    )
    code = EXIT_ERROR
    try:
        loop.run(task, start_payload=start_payload_for(config, start_commit=start_commit))
        if patch_path is not None:
            write_patch(executor, patch_path)
        snapshot = compute_telemetry(event_log.events, config=config)
        code = _exit_for(snapshot["outcome"], headless=headless)
    except Exception as exc:
        event_log(
            EVENT_AGENT_END,
            {"error": redact_secrets(str(exc), config.api_key)},
        )
        print(redact_secrets(str(exc), config.api_key), file=sys.stderr)
        code = EXIT_ERROR
    finally:
        events = load_events(event_log.path) or event_log.events
        write_telemetry(telemetry_path, compute_telemetry(events, config=config))
    return code


def run_interactive(
    args: argparse.Namespace,
    *,
    provider: Provider | None = None,
    config: Config | None = None,
) -> int:
    cwd = Path(args.cwd).resolve()
    config = config or load_config(Path(args.config) if args.config else None, cwd=cwd)
    if provider is None and not config.api_key:
        print("DEEPSEEK_API_KEY is not set", file=sys.stderr)
        return EXIT_STARTUP
    executor = LocalExecutor(cwd)
    try:
        start_commit = prepare_workspace(executor, allow_dirty=args.allow_dirty)
    except StartupError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_STARTUP

    session_dir = Path(args.session_dir) if args.session_dir else resolve_session_dir(config, cwd)
    try:
        session, messages = _open_session(
            session_dir,
            continue_session=args.continue_session,
            api_key=config.api_key,
        )
    except StartupError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_STARTUP

    events_path = session.path.with_suffix(".events.jsonl")
    telemetry_path = session.path.with_suffix(".telemetry.json")
    return execute(
        config=config,
        cwd=cwd,
        task=args.task,
        session=session,
        events_path=events_path,
        telemetry_path=telemetry_path,
        provider=provider or DeepSeekProvider(config),
        tools=default_tools(config),
        start_commit=start_commit,
        headless=False,
        executor=executor,
        messages=messages,
        extra_listeners=[_print_tool],
        on_delta=_print_delta,
    )


def run_headless(
    args: argparse.Namespace,
    *,
    provider: Provider | None = None,
    config: Config | None = None,
) -> int:
    cwd = Path(args.cwd).resolve()
    out = Path(args.out).resolve()
    config = config or load_config(Path(args.config) if args.config else None, cwd=cwd)
    if provider is None and not config.api_key:
        print("DEEPSEEK_API_KEY is not set", file=sys.stderr)
        return EXIT_STARTUP
    executor = LocalExecutor(cwd)
    try:
        start_commit = prepare_workspace(executor, allow_dirty=args.allow_dirty)
    except StartupError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_STARTUP

    out.mkdir(parents=True, exist_ok=True)
    session, messages = _open_session(out / "sessions", continue_session=False, api_key=config.api_key)
    return execute(
        config=config,
        cwd=cwd,
        task=args.task,
        session=session,
        events_path=out / "events.jsonl",
        telemetry_path=out / "telemetry.json",
        provider=provider or DeepSeekProvider(config),
        tools=headless_tools(config),
        start_commit=start_commit,
        headless=True,
        executor=executor,
        patch_path=out / "patch.diff",
        messages=messages,
        extra_listeners=[_print_tool],
        on_delta=_print_delta,
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "run":
        return run_headless(parse_run(argv[1:]))
    return run_interactive(parse_interactive(argv))


if __name__ == "__main__":
    raise SystemExit(main())
