import os
from pathlib import Path

from agent0.agent.messages import (
    INTERRUPTED_TOOL,
    AssistantMessage,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from agent0.session import Session


def test_append_only_and_restore_reasoning(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "sessions", session_id="one")
    reasoning = "keep every rune 字 for 字  "
    session.append(SystemMessage("sys"))
    session.append(UserMessage("hi"))
    session.append(
        AssistantMessage(
            content="ok",
            reasoning_content=reasoning,
            tool_calls=[ToolCall("c1", "read", '{"path":"a"}')],
        )
    )
    session.append(ToolResultMessage("c1", "read", "alpha"))
    first = session.path.read_text(encoding="utf-8")
    session.append(UserMessage("again"))
    second = session.path.read_text(encoding="utf-8")
    assert second.startswith(first)
    assert first in second

    loaded = Session(session.path).load()
    assistant = next(m for m in loaded if isinstance(m, AssistantMessage))
    assert assistant.reasoning_content == reasoning
    assert [type(m).__name__ for m in loaded] == [
        "SystemMessage",
        "UserMessage",
        "AssistantMessage",
        "ToolResultMessage",
        "UserMessage",
    ]


def test_key_not_written_to_jsonl(tmp_path: Path) -> None:
    key = "sk-session-secret-value"
    session = Session.create(tmp_path / "sessions", session_id="sec")
    session.append(
        AssistantMessage(content=f"leak {key}", reasoning_content=f"think {key} and other"),
        api_key=key,
    )
    text = session.path.read_text(encoding="utf-8")
    assert key not in text
    assert "[REDACTED]" in text


def test_restore_unanswered_tool_calls_are_synthesized(tmp_path: Path, executor) -> None:
    session = Session.create(tmp_path / "sessions", session_id="gap")
    session.append(UserMessage("read it"))
    session.append(
        AssistantMessage(
            reasoning_content="will read",
            tool_calls=[
                ToolCall("c1", "read", '{"path":"secret.txt"}'),
                ToolCall("c2", "bash", '{"command":"echo hi"}'),
            ],
        )
    )
    (tmp_path / "secret.txt").write_text("should-not-run", encoding="utf-8")
    loaded = session.load_and_repair()
    results = [m for m in loaded if isinstance(m, ToolResultMessage)]
    assert [m.tool_call_id for m in results] == ["c1", "c2"]
    assert all(m.content == INTERRUPTED_TOOL for m in results)
    assert (tmp_path / "secret.txt").read_text(encoding="utf-8") == "should-not-run"
    # synthesized results were appended, not rewritten
    again = Session(session.path).load()
    assert sum(isinstance(m, ToolResultMessage) for m in again) == 2


def test_continue_ignores_events_sidecar(tmp_path: Path) -> None:
    session_dir = tmp_path / "sessions"
    session = Session.create(session_dir, session_id="abc123")
    session.append(UserMessage("hello"))
    events = session_dir / "abc123.events.jsonl"
    telemetry = session_dir / "abc123.telemetry.json"
    events.write_text('{"event":"agent_start","ts":1,"payload":{}}\n', encoding="utf-8")
    telemetry.write_text("{}\n", encoding="utf-8")
    later = session.path.stat().st_mtime + 30
    os.utime(events, (later, later))
    os.utime(telemetry, (later + 1, later + 1))
    assert Session.latest_path(session_dir) == session.path
    opened = Session.open_latest(session_dir)
    assert opened.path == session.path
    loaded = opened.load()
    assert [type(m).__name__ for m in loaded] == ["UserMessage"]
    assert loaded[0].content == "hello"


def test_truncated_last_line_is_ignored(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "sessions", session_id="half")
    session.append(UserMessage("one"))
    session.append(UserMessage("two"))
    with session.path.open("a", encoding="utf-8") as handle:
        handle.write('{"id":"3","parent_id":"2","type":"user","content":"par')
    reopened = Session(session.path)
    messages = reopened.load()
    assert [m.content for m in messages if isinstance(m, UserMessage)] == ["one", "two"]
    assert reopened.warnings
    assert "truncated last JSONL line" in reopened.warnings[0]
