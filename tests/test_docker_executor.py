from __future__ import annotations

import os
import subprocess

import pytest

from agent0.executors.docker import CONDA_PREFIX, DockerExecutor, official_instance_image
from agent0.workspace import prepare_workspace, write_patch
from tests.dockerutil import docker_available

needs_docker = pytest.mark.skipif(not docker_available(), reason="docker not available")

PYTHON_IMAGE = "python:3.12-slim"
GIT_IMAGE = "agent0-test:git"


def test_official_instance_image_matches_harness() -> None:
    assert official_instance_image("django__django-11790") == (
        "swebench/sweb.eval.x86_64.django_1776_django-11790"
    )
    assert official_instance_image(
        "django__django-11790",
        prefix="reg.example/sweb.eval.x86_64.",
    ) == "reg.example/sweb.eval.x86_64.django_1776_django-11790"


def test_exec_argv_activates_conda() -> None:
    executor = DockerExecutor("img", activate_conda=True, name="n")
    argv = executor.exec_argv("python -c 'print(1)'")
    assert argv[-3:-1] == ["bash", "-lc"]
    assert argv[-1].startswith(CONDA_PREFIX)
    assert "python -c" in argv[-1]


@needs_docker
def test_write_read_via_stdin_and_no_host_key() -> None:
    os.environ["DEEPSEEK_API_KEY"] = "sk-should-not-enter-container"
    with DockerExecutor(
        PYTHON_IMAGE,
        workdir="/work",
        network=False,
        activate_conda=False,
    ) as executor:
        executor.write_text("note.txt", "hello $WORLD and 'quotes'\n")
        assert executor.read_text("note.txt") == "hello $WORLD and 'quotes'\n"
        env = executor.run("printenv", timeout=30)
        assert "DEEPSEEK_API_KEY" not in env.stdout
        inspect = subprocess.run(
            ["docker", "inspect", "-f", "{{.HostConfig.NetworkMode}}", executor.name],
            check=True,
            capture_output=True,
            text=True,
        )
        assert inspect.stdout.strip() == "none"
        name = executor.name
    gone = subprocess.run(["docker", "inspect", name], capture_output=True, text=True)
    assert gone.returncode != 0


@needs_docker
def test_workspace_git_runs_inside_container(tmp_path) -> None:
    with DockerExecutor(
        GIT_IMAGE,
        workdir="/work",
        network=False,
        activate_conda=False,
    ) as executor:
        setup = executor.run(
            "git init && git config user.email t@t && git config user.name t "
            "&& git config commit.gpgsign false",
            timeout=30,
        )
        assert setup.exit_code == 0, setup.stderr
        executor.write_text("tracked.py", "old\n")
        commit = executor.run("git add -A && git commit -m init", timeout=30)
        assert commit.exit_code == 0, commit.stderr
        prepare_workspace(executor, allow_dirty=False)
        executor.write_text("tracked.py", "new\n")
        executor.write_text("fresh.py", "hello\n")
        executor.write_text(".agent/artifacts/skip.txt", "nope\n")
        dest = tmp_path / "patch.diff"
        text = write_patch(executor, dest)
        assert "fresh.py" in text
        assert "hello" in text
        assert ".agent" not in text
        cached = executor.run("git diff --cached", timeout=30)
        assert cached.stdout == ""
        status = executor.run("git status --porcelain", timeout=30)
        assert ".agent" not in status.stdout
    assert dest.is_file()
