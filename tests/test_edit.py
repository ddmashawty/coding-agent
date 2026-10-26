from pathlib import Path

from agent0.tools.edit import EditTool


def test_edit_unique_match_returns_diff(executor, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    out = EditTool().run(
        executor,
        {"path": "a.txt", "old_string": "beta", "new_string": "gamma"},
    )
    assert "beta" in out and "gamma" in out
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "alpha\ngamma\n"


def test_edit_missing_string_does_not_change(executor, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("only-once\n", encoding="utf-8")
    out = EditTool().run(
        executor,
        {"path": "a.txt", "old_string": "missing", "new_string": "x"},
    )
    assert out.startswith("Error:")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "only-once\n"


def test_edit_non_unique_match_errors(executor, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("foo bar foo\n", encoding="utf-8")
    out = EditTool().run(
        executor,
        {"path": "a.txt", "old_string": "foo", "new_string": "baz"},
    )
    assert "unique" in out
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "foo bar foo\n"
