from pathlib import Path

from agent0.tools.bash import BashTool


def test_bash_success(executor) -> None:
    out = BashTool().run(executor, {"command": "printf hello"})
    assert "exit_code=0" in out
    assert "hello" in out


def test_bash_nonzero(executor) -> None:
    out = BashTool().run(executor, {"command": "exit 7"})
    assert "exit_code=7" in out


def test_bash_timeout(executor) -> None:
    out = BashTool(default_timeout=120).run(
        executor, {"command": "sleep 5", "timeout": 0.2}
    )
    assert "timed out" in out


def test_bash_truncates_and_writes_artifact(executor, tmp_path: Path) -> None:
    tool = BashTool(default_timeout=30, head_chars=40, tail_chars=40)
    out = tool.run(executor, {"command": "python3 -c \"print('x'*400)\""})
    assert "truncated" in out
    assert ".agent/artifacts/" in out
    artifacts = list((tmp_path / ".agent" / "artifacts").glob("*.txt"))
    assert len(artifacts) == 1
    full = artifacts[0].read_text(encoding="utf-8")
    assert "xxxx" in full
    assert len(full) > len(out)
