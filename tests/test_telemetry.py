from __future__ import annotations

import json
from pathlib import Path

from agent0.agent.loop import AgentLoop
from agent0.providers.base import ProviderResponse, ToolCallRequest, Usage
from agent0.providers.fake import FakeProvider
from agent0.telemetry import (
    EventLog,
    compute_telemetry,
    load_events,
    write_telemetry,
)
from agent0.tools.registry import headless_tools


def _ev(event: str, payload: dict, ts: float = 1.0) -> dict:
    return {"event": event, "ts": ts, "payload": payload}


def _usage(prompt: int, completion: int = 1) -> dict:
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": prompt,
    }


def test_repeat_read_only_when_content_unchanged() -> None:
    start = _ev("agent_start", {"start_commit": "abc", "soft_line": 60000, "hard_line": 90000})
    unchanged = [
        start,
        _ev("tool_execution_start", {"name": "read", "arguments": {"path": "a.py"}}),
        _ev("tool_execution_end", {"name": "read", "result": "old"}),
        _ev("tool_execution_start", {"name": "read", "arguments": {"path": "a.py"}}),
        _ev("tool_execution_end", {"name": "read", "result": "old"}),
        _ev("agent_end", {}),
    ]
    assert compute_telemetry(unchanged)["repeat_reads"] == 1

    edited = [
        start,
        _ev("tool_execution_start", {"name": "read", "arguments": {"path": "a.py"}}),
        _ev("tool_execution_end", {"name": "read", "result": "old"}),
        _ev("tool_execution_start", {"name": "edit", "arguments": {"path": "a.py"}}),
        _ev("tool_execution_end", {"name": "edit", "result": "--- a.py\n+++ a.py\n"}),
        _ev("tool_execution_start", {"name": "read", "arguments": {"path": "a.py"}}),
        _ev("tool_execution_end", {"name": "read", "result": "new"}),
        _ev("agent_end", {}),
    ]
    assert compute_telemetry(edited)["repeat_reads"] == 0


def test_retry_failed_command_requires_no_write_edit_in_between() -> None:
    start = _ev("agent_start", {"start_commit": "abc", "soft_line": 60000, "hard_line": 90000})
    fail_then_retry = [
        start,
        _ev("tool_execution_start", {"name": "bash", "arguments": {"command": "pytest"}}),
        _ev("tool_execution_end", {"name": "bash", "result": "exit_code=1\nfail\n"}),
        _ev("tool_execution_start", {"name": "bash", "arguments": {"command": "pytest"}}),
        _ev("tool_execution_end", {"name": "bash", "result": "exit_code=1\nfail\n"}),
        _ev("agent_end", {}),
    ]
    assert compute_telemetry(fail_then_retry)["retry_failed_commands"] == 1

    fail_edit_retry = [
        start,
        _ev("tool_execution_start", {"name": "bash", "arguments": {"command": "pytest"}}),
        _ev("tool_execution_end", {"name": "bash", "result": "exit_code=1\nfail\n"}),
        _ev("tool_execution_start", {"name": "edit", "arguments": {"path": "a.py"}}),
        _ev("tool_execution_end", {"name": "edit", "result": "--- a.py\n+++ a.py\n"}),
        _ev("tool_execution_start", {"name": "bash", "arguments": {"command": "pytest"}}),
        _ev("tool_execution_end", {"name": "bash", "result": "exit_code=0\npass\n"}),
        _ev("agent_end", {}),
    ]
    assert compute_telemetry(fail_edit_retry)["retry_failed_commands"] == 0


def test_soft_hard_line_counts_crossings_once() -> None:
    events = [
        _ev("agent_start", {"start_commit": "abc", "soft_line": 60000, "hard_line": 90000}, ts=1),
        _ev("turn_start", {"step": 0}, ts=2),
        _ev("message_end", {"finish_reason": "tool_calls", "usage": _usage(50_000)}, ts=3),
        _ev("turn_start", {"step": 1}, ts=4),
        _ev("message_end", {"finish_reason": "tool_calls", "usage": _usage(61_000)}, ts=5),
        _ev("turn_start", {"step": 2}, ts=6),
        _ev("message_end", {"finish_reason": "stop", "usage": _usage(62_000)}, ts=7),
        _ev("agent_end", {}, ts=8),
    ]
    snap = compute_telemetry(events)
    assert snap["soft_line_hits"] == 1
    assert snap["hard_line_hits"] == 0
    assert snap["turns"] == 3
    assert snap["tokens"]["prompt"] == 50_000 + 61_000 + 62_000
    assert snap["duration_seconds"] == 7.0
    assert snap["start_commit"] == "abc"


def test_outcome_priority_and_reconstruction(tmp_path: Path) -> None:
    events = [
        _ev("agent_start", {"start_commit": "deadbeef", "soft_line": 60000, "hard_line": 90000}),
        _ev("tool_execution_start", {"name": "submit", "arguments": {"summary": "done"}}),
        _ev("tool_execution_end", {"name": "submit", "result": "done"}),
        _ev("agent_end", {"submitted": True, "max_steps_hit": False, "steps": 1}),
    ]
    log = EventLog(tmp_path / "events.jsonl")
    for item in events:
        log(item["event"], item["payload"])
    from_memory = compute_telemetry(log.events)
    from_disk = compute_telemetry(load_events(log.path))
    assert from_memory["outcome"] == from_disk["outcome"] == "submitted"
    tel = tmp_path / "telemetry.json"
    write_telemetry(tel, from_disk)
    assert json.loads(tel.read_text(encoding="utf-8")) == from_disk

    errored = events[:-1] + [_ev("agent_end", {"error": "boom", "submitted": True})]
    assert compute_telemetry(errored)["outcome"] == "error"
    capped = [_ev("agent_end", {"max_steps_hit": True, "submitted": False})]
    assert compute_telemetry(capped)["outcome"] == "max_steps"
    idle = [_ev("agent_end", {})]
    assert compute_telemetry(idle)["outcome"] == "no_submit"


def test_loop_read_edit_read_is_not_repeat(config, executor, tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("old", encoding="utf-8")
    events: list[tuple[str, dict]] = []

    def listener(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    loop = AgentLoop(
        config=config,
        provider=FakeProvider(
            [
                ProviderResponse(
                    "",
                    "r1",
                    [ToolCallRequest("c1", "read", '{"path":"a.py"}')],
                    "tool_calls",
                ),
                ProviderResponse(
                    "",
                    "r2",
                    [
                        ToolCallRequest(
                            "c2",
                            "edit",
                            '{"path":"a.py","old_string":"old","new_string":"new"}',
                        )
                    ],
                    "tool_calls",
                ),
                ProviderResponse(
                    "",
                    "r3",
                    [ToolCallRequest("c3", "read", '{"path":"a.py"}')],
                    "tool_calls",
                ),
                ProviderResponse("done", "r4", [], "stop"),
            ]
        ),
        executor=executor,
        tools=headless_tools(config),
        listeners=[listener],
    )
    loop.run("fix")
    records = [{"event": name, "ts": i, "payload": payload} for i, (name, payload) in enumerate(events)]
    assert compute_telemetry(records, config=config)["repeat_reads"] == 0


def test_loop_soft_line_from_usage(config, executor) -> None:
    events: list[tuple[str, dict]] = []

    def listener(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    def usage(prompt: int) -> Usage:
        return Usage(_usage(prompt))

    loop = AgentLoop(
        config=config,
        provider=FakeProvider(
            [
                ProviderResponse("a", "r1", [], "stop", usage=usage(50_000)),
            ]
        ),
        executor=executor,
        tools=headless_tools(config),
        listeners=[listener],
    )
    # one stop ends the loop; crossing test uses synthetic events above.
    loop.run("hi", start_payload={"start_commit": "x", "soft_line": 60000, "hard_line": 90000})
    records = [{"event": name, "ts": i, "payload": payload} for i, (name, payload) in enumerate(events)]
    snap = compute_telemetry(records, config=config)
    assert snap["soft_line_hits"] == 0
    assert snap["start_commit"] == "x"


def test_event_log_ignores_truncated_last_line(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    log("turn_start", {"step": 0})
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"event":"turn_end","ts":1,"payload":')
    loaded = load_events(path)
    assert [item["event"] for item in loaded] == ["turn_start"]
