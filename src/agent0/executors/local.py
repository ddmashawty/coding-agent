from __future__ import annotations

import os
import subprocess
from pathlib import Path

from agent0.executors.base import CommandResult, Executor


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("DEEPSEEK_API_KEY", None)
    return env


class LocalExecutor(Executor):
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()

    def _resolve(self, path: str) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.cwd / candidate
        return candidate

    def run(self, command: str, *, timeout: float) -> CommandResult:
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_child_env(),
            )
            return CommandResult(
                command=command,
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return CommandResult(
                command=command,
                exit_code=-1,
                stdout=stdout,
                stderr=stderr,
                timed_out=True,
            )

    def read_text(self, path: str) -> str:
        target = self._resolve(path)
        return target.read_text(encoding="utf-8")

    def write_text(self, path: str, content: str) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
