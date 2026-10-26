from pathlib import Path

from agent0.executors.local import LocalExecutor


def test_run_and_read_respect_cwd(tmp_path: Path) -> None:
    nested = tmp_path / "work"
    nested.mkdir()
    (nested / "a.txt").write_text("inside", encoding="utf-8")
    (tmp_path / "a.txt").write_text("outside", encoding="utf-8")
    executor = LocalExecutor(nested)
    assert executor.read_text("a.txt") == "inside"
    result = executor.run("pwd", timeout=5)
    assert result.exit_code == 0
    assert str(nested) in result.stdout


def test_write_text_creates_parents(tmp_path: Path) -> None:
    executor = LocalExecutor(tmp_path)
    executor.write_text(".agent/artifacts/x.txt", "payload")
    assert (tmp_path / ".agent" / "artifacts" / "x.txt").read_text(encoding="utf-8") == "payload"


def test_subprocess_env_omits_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-must-not-leak-into-child")
    executor = LocalExecutor(tmp_path)
    result = executor.run("printenv DEEPSEEK_API_KEY", timeout=5)
    assert "sk-must-not-leak-into-child" not in result.stdout
    assert "sk-must-not-leak-into-child" not in result.stderr
