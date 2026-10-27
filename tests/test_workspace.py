from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent0.workspace import StartupError, prepare_workspace, write_patch
from tests.gitrepo import init_git_repo


def _porcelain(cwd: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _cached(cwd: Path) -> str:
    return subprocess.run(
        ["git", "diff", "--cached"],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_prepare_requires_git(tmp_path: Path) -> None:
    with pytest.raises(StartupError, match="not a git repository"):
        prepare_workspace(tmp_path, allow_dirty=False)


def test_prepare_rejects_dirty(tmp_path: Path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    (repo / "README").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(StartupError, match="dirty"):
        prepare_workspace(repo, allow_dirty=False)
    commit = prepare_workspace(repo, allow_dirty=True)
    assert len(commit) >= 7


def test_exclude_hides_agent_dir(tmp_path: Path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    prepare_workspace(repo, allow_dirty=False)
    artifact = repo / ".agent" / "artifacts" / "out.txt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("noise\n", encoding="utf-8")
    assert _porcelain(repo) == ""


def test_patch_includes_untracked_and_leaves_index(tmp_path: Path) -> None:
    repo = init_git_repo(tmp_path / "repo", {"tracked.py": "old\n"})
    prepare_workspace(repo, allow_dirty=False)
    (repo / "tracked.py").write_text("new\n", encoding="utf-8")
    (repo / "fresh.py").write_text("hello\n", encoding="utf-8")
    (repo / ".agent" / "artifacts" / "skip.txt").parent.mkdir(parents=True, exist_ok=True)
    (repo / ".agent" / "artifacts" / "skip.txt").write_text("nope\n", encoding="utf-8")
    dest = tmp_path / "patch.diff"
    text = write_patch(repo, dest)
    assert dest.read_text(encoding="utf-8") == text
    assert "fresh.py" in text
    assert "hello" in text
    assert "tracked.py" in text
    assert ".agent" not in text
    assert _cached(repo) == ""
    assert "fresh.py" in _porcelain(repo)
