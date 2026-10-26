from __future__ import annotations

from pathlib import Path

import pytest

from agent0.config import Config
from agent0.executors.local import LocalExecutor
from agent0.tools.registry import default_tools


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        model="deepseek-flash",
        base_url="https://api.deepseek.com",
        api_key="sk-test-not-a-real-key-12345678",
        context_window=1_000_000,
        soft_ratio=0.5,
        soft_abs=60_000,
        hard_ratio=0.7,
        hard_abs=90_000,
        keep_turns=6,
        consecutive_fail_record=3,
        consecutive_fail_escalate=5,
        thinking="enabled",
        bash_timeout_seconds=120,
        max_steps=16,
        bash_truncate_head=80,
        bash_truncate_tail=80,
        session_dir=".agent/sessions",
        config_path=tmp_path / "agent.toml",
    )


@pytest.fixture
def executor(tmp_path: Path) -> LocalExecutor:
    return LocalExecutor(tmp_path)


@pytest.fixture
def tools(config: Config):
    return default_tools(config)
