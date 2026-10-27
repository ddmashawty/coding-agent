"""Git workspace checks and patch.diff. Never touches the real index."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


class StartupError(Exception):
    """Workspace is not ready. CLI maps this to exit code 2."""


def _git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("DEEPSEEK_API_KEY", None)
    if extra:
        env.update(extra)
    return env


def git(cwd: Path, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=_git_env(extra_env),
    )


def is_git_worktree(cwd: Path) -> bool:
    result = git(cwd, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def head_commit(cwd: Path) -> str:
    result = git(cwd, "rev-parse", "HEAD")
    if result.returncode != 0:
        raise StartupError("workspace has no HEAD commit")
    return result.stdout.strip()


def git_dir(cwd: Path) -> Path:
    result = git(cwd, "rev-parse", "--git-dir")
    if result.returncode != 0:
        raise StartupError(f"not a git repository: {cwd}")
    path = Path(result.stdout.strip())
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()


def ensure_agent_excluded(cwd: Path) -> None:
    """Append .agent/ to .git/info/exclude. Does not change the index."""
    exclude = git_dir(cwd) / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    markers = {line.strip() for line in existing.splitlines()}
    if ".agent/" in markers or ".agent" in markers:
        return
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    with exclude.open("a", encoding="utf-8") as handle:
        handle.write(f"{prefix}.agent/\n")


def is_dirty(cwd: Path) -> bool:
    result = git(cwd, "status", "--porcelain")
    if result.returncode != 0:
        raise StartupError(result.stderr.strip() or "git status failed")
    return bool(result.stdout.strip())


def prepare_workspace(cwd: Path, *, allow_dirty: bool) -> str:
    if not is_git_worktree(cwd):
        raise StartupError(f"not a git repository: {cwd}")
    ensure_agent_excluded(cwd)
    commit = head_commit(cwd)
    if not allow_dirty and is_dirty(cwd):
        raise StartupError("working tree is dirty; pass --allow-dirty to proceed")
    return commit


def write_patch(cwd: Path, dest: Path) -> str:
    """Diff vs HEAD including untracked files, without modifying the real index."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    ensure_agent_excluded(cwd)
    with tempfile.TemporaryDirectory(prefix="agent0-index-") as tmp:
        index = Path(tmp) / "index"
        extra = {"GIT_INDEX_FILE": str(index.resolve())}
        read = git(cwd, "read-tree", "HEAD", extra_env=extra)
        if read.returncode != 0:
            raise RuntimeError(read.stderr.strip() or "git read-tree failed")
        # Rely on .git/info/exclude for .agent/. Do not pass .agent as a
        # pathspec: naming an ignored path makes git add exit 1.
        added = git(cwd, "-c", "advice.addIgnoredFile=false", "add", "-A", extra_env=extra)
        if added.returncode != 0:
            raise RuntimeError(added.stderr.strip() or "git add failed")
        diff = git(cwd, "diff", "--cached", "HEAD", extra_env=extra)
        if diff.returncode != 0:
            raise RuntimeError(diff.stderr.strip() or "git diff --cached failed")
        text = diff.stdout
    dest.write_text(text, encoding="utf-8")
    return text
