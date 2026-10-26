from pathlib import Path

from agent0.tools.read import ReadTool


def test_read_existing_file(executor, tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    out = ReadTool().run(executor, {"path": "note.txt"})
    assert out == "hello"


def test_read_missing_file(executor) -> None:
    out = ReadTool().run(executor, {"path": "nope.txt"})
    assert out.startswith("Error:")
    assert "not found" in out


def test_read_uses_executor_only(monkeypatch, executor, tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("via-exec", encoding="utf-8")
    called = []
    original = executor.read_text

    def wrapped(path: str) -> str:
        called.append(path)
        return original(path)

    monkeypatch.setattr(executor, "read_text", wrapped)
    ReadTool().run(executor, {"path": "note.txt"})
    assert called == ["note.txt"]
