"""Git workspace checks and patch.diff. All git goes through the executor."""

from __future__ import annotations

import shlex
from pathlib import Path

from agent0.executors.base import CommandResult, Executor

PATCH_INDEX = "/tmp/agent0-patch-index"


class StartupError(Exception):
    """Workspace is not ready. CLI maps this to exit code 2."""


def run_git(
    executor: Executor,
    *args: str,
    extra_env: dict[str, str] | None = None,
    timeout: float = 60,
) -> CommandResult:
    parts: list[str] = []
    if extra_env:
        for key, value in extra_env.items():
            parts.append(f"{key}={shlex.quote(value)}")
    parts.append("git")
    parts.extend(shlex.quote(arg) for arg in args)
    return executor.run(" ".join(parts), timeout=timeout)


def is_git_worktree(executor: Executor) -> bool:
    result = run_git(executor, "rev-parse", "--is-inside-work-tree")
    return result.exit_code == 0 and result.stdout.strip() == "true"


def head_commit(executor: Executor) -> str:
    result = run_git(executor, "rev-parse", "HEAD")
    if result.exit_code != 0:
        raise StartupError(result.stderr.strip() or "workspace has no HEAD commit")
    return result.stdout.strip()


def git_dir(executor: Executor) -> str:
    result = run_git(executor, "rev-parse", "--git-dir")
    if result.exit_code != 0:
        raise StartupError(result.stderr.strip() or "not a git repository")
    return result.stdout.strip()


def ensure_agent_excluded(executor: Executor) -> None:
    """Append .agent/ to .git/info/exclude. Does not change the index."""
    exclude_path = str(Path(git_dir(executor)) / "info" / "exclude")
    try:
        existing = executor.read_text(exclude_path)
    except FileNotFoundError:
        existing = ""
    markers = {line.strip() for line in existing.splitlines()}
    if ".agent/" in markers or ".agent" in markers:
        return
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    executor.write_text(exclude_path, f"{existing}{prefix}.agent/\n")


def is_dirty(executor: Executor) -> bool:
    result = run_git(executor, "status", "--porcelain")
    if result.exit_code != 0:
        raise StartupError(result.stderr.strip() or "git status failed")
    return bool(result.stdout.strip())


def prepare_workspace(executor: Executor, *, allow_dirty: bool) -> str:
    if not is_git_worktree(executor):
        raise StartupError("not a git repository")
    ensure_agent_excluded(executor)
    commit = head_commit(executor)
    if not allow_dirty and is_dirty(executor):
        raise StartupError("working tree is dirty; pass --allow-dirty to proceed")
    return commit


def write_patch(executor: Executor, dest: Path) -> str:
    """Diff vs HEAD including untracked files, without modifying the real index.

    The temp index lives in the executor filesystem (container or host).
    dest is on the host.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    ensure_agent_excluded(executor)
    extra = {"GIT_INDEX_FILE": PATCH_INDEX}
    executor.run(f"rm -f {shlex.quote(PATCH_INDEX)}", timeout=30)
    read = run_git(executor, "read-tree", "HEAD", extra_env=extra)
    if read.exit_code != 0:
        raise RuntimeError(read.stderr.strip() or "git read-tree failed")
    added = run_git(
        executor,
        "-c",
        "advice.addIgnoredFile=false",
        "add",
        "-A",
        extra_env=extra,
    )
    if added.exit_code != 0:
        raise RuntimeError(added.stderr.strip() or "git add failed")
    diff = run_git(executor, "diff", "--cached", "HEAD", extra_env=extra)
    if diff.exit_code != 0:
        raise RuntimeError(diff.stderr.strip() or "git diff --cached failed")
    text = diff.stdout
    dest.write_text(text, encoding="utf-8")
    return text
