"""Docker CLI executor. No SDK. Work happens in a container; --out stays on the host."""

from __future__ import annotations

import secrets
import subprocess
from pathlib import Path

from agent0.executors.base import CommandResult, Executor

# Official SWE-bench instance images (see swebench/harness/dockerfiles/python.py):
# PATH includes /opt/miniconda3/bin; .bashrc activates conda env "testbed".
# docker exec is not a login shell, so we source this before user commands.
CONDA_PREFIX = (
    "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && "
)


def official_instance_image(
    instance_id: str,
    *,
    namespace: str = "swebench",
    arch: str = "x86_64",
    prefix: str | None = None,
) -> str:
    """Remote image name used by the official harness when --namespace is swebench.

    `prefix`, if set, is everything before the instance slug (for example
    `swebench/sweb.eval.x86_64.`). The slug is `instance_id.lower()` with
    `__` rewritten to `_1776_`.
    """
    slug = instance_id.lower().replace("__", "_1776_")
    if prefix:
        return f"{prefix}{slug}"
    return f"{namespace}/sweb.eval.{arch}.{slug}"


def _sanitize_name(raw: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in raw)
    return cleaned[:80] or "box"


class DockerExecutor(Executor):
    def __init__(
        self,
        image: str,
        *,
        workdir: str = "/testbed",
        network: bool = False,
        activate_conda: bool = True,
        name: str | None = None,
    ) -> None:
        self.image = image
        self.workdir = workdir
        self.network = network
        self.activate_conda = activate_conda
        suffix = secrets.token_hex(4)
        self.name = name or f"agent0-{_sanitize_name(image.split('/')[-1])}-{suffix}"
        self._started = False

    def __enter__(self) -> DockerExecutor:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        if self._started:
            return
        network = "bridge" if self.network else "none"
        argv = [
            "docker",
            "run",
            "-d",
            "--name",
            self.name,
            "--network",
            network,
            "--workdir",
            self.workdir,
            "--entrypoint",
            "sleep",
            self.image,
            "infinity",
        ]
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "docker run failed")
        self._started = True

    def close(self) -> None:
        if not self._started:
            return
        subprocess.run(
            ["docker", "rm", "-f", self.name],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self._started = False

    def exec_argv(self, command: str) -> list[str]:
        if self.activate_conda:
            return ["docker", "exec", "-w", self.workdir, self.name, "bash", "-lc", CONDA_PREFIX + command]
        return ["docker", "exec", "-w", self.workdir, self.name, "sh", "-c", command]

    def _docker(self, argv: list[str], *, timeout: float, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            timeout=timeout,
        )

    def run(self, command: str, *, timeout: float) -> CommandResult:
        if not self._started:
            raise RuntimeError("DockerExecutor is not started")
        try:
            completed = self._docker(self.exec_argv(command), timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
            stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
            return CommandResult(command, -1, stdout, stderr, timed_out=True)
        return CommandResult(
            command=command,
            exit_code=completed.returncode,
            stdout=completed.stdout.decode("utf-8", errors="replace"),
            stderr=completed.stderr.decode("utf-8", errors="replace"),
        )

    def _container_path(self, path: str) -> str:
        candidate = Path(path)
        if candidate.is_absolute():
            return str(candidate)
        return str(Path(self.workdir) / candidate)

    def read_text(self, path: str) -> str:
        target = self._container_path(path)
        if not self._started:
            raise RuntimeError("DockerExecutor is not started")
        completed = self._docker(
            ["docker", "exec", self.name, "cat", "--", target],
            timeout=30,
        )
        if completed.returncode != 0:
            err = completed.stderr.decode("utf-8", errors="replace")
            raise FileNotFoundError(err or target)
        return completed.stdout.decode("utf-8")

    def write_text(self, path: str, content: str) -> None:
        """Write via stdin so content is never interpolated by a shell."""
        target = self._container_path(path)
        if not self._started:
            raise RuntimeError("DockerExecutor is not started")
        script = 'mkdir -p -- "$(dirname -- "$1")" && cat > "$1"'
        completed = self._docker(
            ["docker", "exec", "-i", self.name, "sh", "-c", script, "write_text", target],
            timeout=30,
            stdin=content.encode("utf-8"),
        )
        if completed.returncode != 0:
            err = completed.stderr.decode("utf-8", errors="replace")
            raise OSError(err or f"cannot write {target}")
