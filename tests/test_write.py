from pathlib import Path

from agent0.tools.write import WriteTool


def test_write_creates_file(executor, tmp_path: Path) -> None:
    out = WriteTool().run(executor, {"path": "out.txt", "content": "hello"})
    assert "wrote" in out
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hello"


def test_write_overwrites(executor, tmp_path: Path) -> None:
    (tmp_path / "out.txt").write_text("old", encoding="utf-8")
    WriteTool().run(executor, {"path": "out.txt", "content": "new"})
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "new"


def test_write_uses_executor_only(monkeypatch, executor, tmp_path: Path) -> None:
    called = []
    original = executor.write_text

    def wrapped(path: str, content: str) -> None:
        called.append((path, content))
        return original(path, content)

    monkeypatch.setattr(executor, "write_text", wrapped)
    WriteTool().run(executor, {"path": "a.txt", "content": "x"})
    assert called == [("a.txt", "x")]
