from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from dataclasses import replace
from pathlib import Path

from agent0.cli import (
    EXIT_ERROR,
    EXIT_MAX_STEPS,
    EXIT_NO_SUBMIT,
    EXIT_OK,
    EXIT_STARTUP,
    parse_run,
    run_headless,
    run_interactive,
)
from agent0.providers.base import ProviderResponse, ToolCallRequest
from agent0.providers.fake import FakeProvider
from agent0.telemetry import compute_telemetry, load_events
from tests.gitrepo import init_git_repo

FIXTURE = Path(__file__).parent / "fixtures" / "buggy_repo"


def _run_ns(cwd: Path, out: Path, task: str = "fix the bug", allow_dirty: bool = False) -> Namespace:
    return Namespace(
        task=task,
        cwd=str(cwd),
        out=str(out),
        config=None,
        allow_dirty=allow_dirty,
        no_rebuild=False,
    )


def _interactive_ns(cwd: Path, task: str = "hello", allow_dirty: bool = False) -> Namespace:
    return Namespace(
        task=task,
        cwd=str(cwd),
        config=None,
        continue_session=False,
        session_dir=None,
        allow_dirty=allow_dirty,
    )


def _porcelain(cwd: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_run_parser_accepts_no_rebuild() -> None:
    args = parse_run(["--task", "t", "--out", "o", "--no-rebuild"])
    assert args.no_rebuild is True
    assert args.out == "o"


def test_startup_not_git(tmp_path: Path, config) -> None:
    out = tmp_path / "out"
    code = run_headless(
        _run_ns(tmp_path, out),
        provider=FakeProvider([ProviderResponse("x", "r", [], "stop")]),
        config=config,
    )
    assert code == EXIT_STARTUP
    assert not out.exists()


def test_startup_dirty(tmp_path: Path, config) -> None:
    repo = init_git_repo(tmp_path / "repo")
    (repo / "README").write_text("dirty\n", encoding="utf-8")
    out = tmp_path / "out"
    code = run_headless(
        _run_ns(repo, out),
        provider=FakeProvider([ProviderResponse("x", "r", [], "stop")]),
        config=config,
    )
    assert code == EXIT_STARTUP


def test_headless_fixes_buggy_repo(tmp_path: Path, config) -> None:
    repo = init_git_repo(
        tmp_path / "repo",
        {
            "add.py": (FIXTURE / "add.py").read_text(encoding="utf-8"),
            "test_add.py": (FIXTURE / "test_add.py").read_text(encoding="utf-8"),
        },
    )
    out = tmp_path / "out"
    provider = FakeProvider(
        [
            ProviderResponse(
                "",
                "read",
                [ToolCallRequest("c1", "read", '{"path":"add.py"}')],
                "tool_calls",
            ),
            ProviderResponse(
                "",
                "edit",
                [
                    ToolCallRequest(
                        "c2",
                        "edit",
                        '{"path":"add.py","old_string":"return a - b","new_string":"return a + b"}',
                    )
                ],
                "tool_calls",
            ),
            ProviderResponse(
                "",
                "check",
                [
                    ToolCallRequest(
                        "c3",
                        "bash",
                        '{"command":"python -c \\"from add import add; assert add(1, 2) == 3\\""}',
                    )
                ],
                "tool_calls",
            ),
            ProviderResponse(
                "",
                "done",
                [ToolCallRequest("s1", "submit", '{"summary":"fixed add"}')],
                "tool_calls",
            ),
        ]
    )
    code = run_headless(_run_ns(repo, out), provider=provider, config=config)
    assert code == EXIT_OK
    assert "return a + b" in (repo / "add.py").read_text(encoding="utf-8")
    patch = (out / "patch.diff").read_text(encoding="utf-8")
    assert "add.py" in patch
    assert "return a + b" in patch
    tel = json.loads((out / "telemetry.json").read_text(encoding="utf-8"))
    assert tel == compute_telemetry(load_events(out / "events.jsonl"), config=config)
    assert tel["outcome"] == "submitted"
    assert tel["start_commit"]
    assert list((out / "sessions").glob("*.jsonl"))
    assert not (repo / ".agent" / "sessions").exists()
    events = load_events(out / "events.jsonl")
    names = {item["event"] for item in events}
    assert {
        "agent_start",
        "turn_start",
        "message_start",
        "message_end",
        "tool_execution_start",
        "tool_execution_end",
        "turn_end",
        "agent_end",
    } <= names
    assert config.api_key not in (out / "events.jsonl").read_text(encoding="utf-8")
    assert config.api_key not in (out / "telemetry.json").read_text(encoding="utf-8")


def test_patch_includes_new_file_from_write(tmp_path: Path, config) -> None:
    repo = init_git_repo(tmp_path / "repo")
    out = tmp_path / "out"
    provider = FakeProvider(
        [
            ProviderResponse(
                "",
                "write",
                [ToolCallRequest("c1", "write", '{"path":"fresh.py","content":"hello\\n"}')],
                "tool_calls",
            ),
            ProviderResponse(
                "",
                "done",
                [ToolCallRequest("s1", "submit", '{"summary":"added file"}')],
                "tool_calls",
            ),
        ]
    )
    code = run_headless(_run_ns(repo, out), provider=provider, config=config)
    assert code == EXIT_OK
    patch = (out / "patch.diff").read_text(encoding="utf-8")
    assert "fresh.py" in patch
    assert "hello" in patch
    cached = subprocess.run(
        ["git", "diff", "--cached"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert cached == ""


def test_artifacts_only_leaves_git_clean(tmp_path: Path, config) -> None:
    repo = init_git_repo(tmp_path / "repo")
    out = tmp_path / "out"
    provider = FakeProvider(
        [
            ProviderResponse(
                "",
                "write",
                [
                    ToolCallRequest(
                        "c1",
                        "write",
                        '{"path":".agent/artifacts/log.txt","content":"only harness output"}',
                    )
                ],
                "tool_calls",
            ),
            ProviderResponse(
                "",
                "done",
                [ToolCallRequest("s1", "submit", '{"summary":"no source changes"}')],
                "tool_calls",
            ),
        ]
    )
    code = run_headless(_run_ns(repo, out), provider=provider, config=config)
    assert code == EXIT_OK
    assert (repo / ".agent" / "artifacts" / "log.txt").is_file()
    assert _porcelain(repo) == ""
    patch = (out / "patch.diff").read_text(encoding="utf-8")
    assert ".agent" not in patch


def test_no_submit_exit_4(tmp_path: Path, config) -> None:
    repo = init_git_repo(tmp_path / "repo")
    out = tmp_path / "out"
    code = run_headless(
        _run_ns(repo, out),
        provider=FakeProvider([ProviderResponse("just text", "r", [], "stop")]),
        config=config,
    )
    assert code == EXIT_NO_SUBMIT
    tel = json.loads((out / "telemetry.json").read_text(encoding="utf-8"))
    assert tel["outcome"] == "no_submit"


def test_max_steps_exit_3(tmp_path: Path, config) -> None:
    repo = init_git_repo(tmp_path / "repo", {"a.txt": "x\n"})
    out = tmp_path / "out"
    cfg = replace(config, max_steps=1)
    provider = FakeProvider(
        [
            ProviderResponse(
                "",
                "r",
                [ToolCallRequest("c1", "read", '{"path":"a.txt"}')],
                "tool_calls",
            ),
            ProviderResponse("should-not-run", "r2", [], "stop"),
        ]
    )
    code = run_headless(_run_ns(repo, out), provider=provider, config=cfg)
    assert code == EXIT_MAX_STEPS
    tel = json.loads((out / "telemetry.json").read_text(encoding="utf-8"))
    assert tel["outcome"] == "max_steps"


def test_crash_exit_1(tmp_path: Path, config) -> None:
    repo = init_git_repo(tmp_path / "repo")
    out = tmp_path / "out"
    code = run_headless(
        _run_ns(repo, out),
        provider=FakeProvider([]),
        config=config,
    )
    assert code == EXIT_ERROR
    assert (out / "events.jsonl").is_file()
    assert (out / "telemetry.json").is_file()
    tel = json.loads((out / "telemetry.json").read_text(encoding="utf-8"))
    assert tel["outcome"] == "error"


def test_interactive_writes_telemetry_beside_session(tmp_path: Path, config) -> None:
    repo = init_git_repo(tmp_path / "repo")
    provider = FakeProvider([ProviderResponse("hi", "r", [], "stop")])
    code = run_interactive(_interactive_ns(repo), provider=provider, config=config)
    assert code == EXIT_OK
    session_dir = repo / ".agent" / "sessions"
    events = list(session_dir.glob("*.events.jsonl"))
    telemetry = list(session_dir.glob("*.telemetry.json"))
    sessions = [
        path
        for path in session_dir.glob("*.jsonl")
        if not path.name.endswith(".events.jsonl")
    ]
    assert len(sessions) == 1
    assert len(events) == 1
    assert len(telemetry) == 1
    snap = json.loads(telemetry[0].read_text(encoding="utf-8"))
    assert snap == compute_telemetry(load_events(events[0]), config=config)
    assert snap["outcome"] == "no_submit"
    assert not (tmp_path / "out").exists()
