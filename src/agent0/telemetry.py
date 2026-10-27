"""Event log and telemetry. Telemetry.json is derived from events.jsonl."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from agent0.config import Config

EXIT_RE = re.compile(r"exit_code=(-?\d+)")

OUTCOME_SUBMITTED = "submitted"
OUTCOME_NO_SUBMIT = "no_submit"
OUTCOME_MAX_STEPS = "max_steps"
OUTCOME_ERROR = "error"


def watermark_limits(config: Config) -> tuple[int, int]:
    soft = min(int(config.context_window * config.soft_ratio), config.soft_abs)
    hard = min(int(config.context_window * config.hard_ratio), config.hard_abs)
    return soft, hard


def start_payload_for(config: Config, *, start_commit: str) -> dict[str, Any]:
    soft, hard = watermark_limits(config)
    return {
        "start_commit": start_commit,
        "soft_line": soft,
        "hard_line": hard,
    }


class EventLog:
    """Append-only JSONL of loop events. Flush each line so crashes keep history."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.events: list[dict[str, Any]] = []
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()

    def __call__(self, event_type: str, payload: dict[str, Any]) -> None:
        record = {"event": event_type, "ts": time.time(), "payload": payload}
        self.events.append(record)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


def load_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    if not text:
        return []
    lines = text.splitlines()
    events: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines) - 1:
                continue
            raise
        if isinstance(record, dict):
            events.append(record)
    return events


def infer_outcome(events: list[dict[str, Any]]) -> str:
    submitted = False
    max_steps_hit = False
    error = False
    for record in events:
        event = record.get("event")
        payload = record.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        if event == "tool_execution_end" and payload.get("name") == "submit":
            submitted = True
        if event == "agent_end":
            if payload.get("error"):
                error = True
            if payload.get("submitted"):
                submitted = True
            if payload.get("max_steps_hit"):
                max_steps_hit = True
    if error:
        return OUTCOME_ERROR
    if max_steps_hit:
        return OUTCOME_MAX_STEPS
    if submitted:
        return OUTCOME_SUBMITTED
    return OUTCOME_NO_SUBMIT


def _tool_succeeded(result: str) -> bool:
    return not result.startswith("Error:")


def compute_telemetry(
    events: list[dict[str, Any]],
    *,
    config: Config | None = None,
) -> dict[str, Any]:
    """Rebuild the telemetry snapshot from an event list. Pure; no I/O."""
    soft_line: int | None = None
    hard_line: int | None = None
    if config is not None:
        soft_line, hard_line = watermark_limits(config)

    start_commit = ""
    turns = 0
    tool_calls = 0
    prompt = completion = cache_hit = cache_miss = 0
    was_soft = False
    was_hard = False
    soft_hits = 0
    hard_hits = 0
    last_read: dict[str, str] = {}
    repeat_reads = 0
    mutation_gen = 0
    last_fail_gen: dict[str, int] = {}
    retries = 0
    pending: tuple[str, dict[str, Any]] | None = None
    first_ts: float | None = None
    last_ts: float | None = None

    for record in events:
        ts = record.get("ts")
        if isinstance(ts, (int, float)):
            if first_ts is None:
                first_ts = float(ts)
            last_ts = float(ts)
        event = record.get("event")
        payload = record.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}

        if event == "agent_start":
            start_commit = str(payload.get("start_commit") or start_commit)
            if payload.get("soft_line") is not None:
                soft_line = int(payload["soft_line"])
            if payload.get("hard_line") is not None:
                hard_line = int(payload["hard_line"])
        elif event == "turn_start":
            turns += 1
        elif event == "message_end":
            usage = payload.get("usage") or {}
            if isinstance(usage, dict):
                prompt += int(usage.get("prompt_tokens") or 0)
                completion += int(usage.get("completion_tokens") or 0)
                cache_hit += int(usage.get("prompt_cache_hit_tokens") or 0)
                cache_miss += int(usage.get("prompt_cache_miss_tokens") or 0)
                tokens = int(usage.get("prompt_tokens") or 0)
                if soft_line is not None:
                    over = tokens >= soft_line
                    if over and not was_soft:
                        soft_hits += 1
                    was_soft = over
                if hard_line is not None:
                    over = tokens >= hard_line
                    if over and not was_hard:
                        hard_hits += 1
                    was_hard = over
        elif event == "tool_execution_start":
            tool_calls += 1
            name = str(payload.get("name") or "")
            arguments = payload.get("arguments") or {}
            if not isinstance(arguments, dict):
                arguments = {}
            pending = (name, arguments)
        elif event == "tool_execution_end":
            name = str(payload.get("name") or "")
            result = payload.get("result")
            result_text = result if isinstance(result, str) else ""
            arguments: dict[str, Any] = {}
            if pending is not None and pending[0] == name:
                arguments = pending[1]
            pending = None

            if name == "read":
                path = arguments.get("path")
                if isinstance(path, str) and _tool_succeeded(result_text):
                    previous = last_read.get(path)
                    if previous is not None and previous == result_text:
                        repeat_reads += 1
                    last_read[path] = result_text
            elif name in {"write", "edit"}:
                if _tool_succeeded(result_text):
                    mutation_gen += 1
            elif name == "bash":
                command = arguments.get("command")
                match = EXIT_RE.search(result_text)
                if isinstance(command, str) and match:
                    exit_code = int(match.group(1))
                    prev_gen = last_fail_gen.get(command)
                    if prev_gen is not None and prev_gen == mutation_gen:
                        retries += 1
                    if exit_code != 0:
                        last_fail_gen[command] = mutation_gen
                    else:
                        last_fail_gen.pop(command, None)

    duration = 0.0
    if first_ts is not None and last_ts is not None:
        duration = last_ts - first_ts

    return {
        "duration_seconds": duration,
        "turns": turns,
        "tool_calls": tool_calls,
        "tokens": {
            "prompt": prompt,
            "completion": completion,
            "cache_hit": cache_hit,
            "cache_miss": cache_miss,
        },
        "soft_line_hits": soft_hits,
        "hard_line_hits": hard_hits,
        "repeat_reads": repeat_reads,
        "retry_failed_commands": retries,
        "user_takeovers": 0,
        "outcome": infer_outcome(events),
        "start_commit": start_commit,
    }


def write_telemetry(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
