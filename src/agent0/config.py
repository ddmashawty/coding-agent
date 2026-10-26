from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    model: str
    base_url: str
    api_key: str
    context_window: int
    soft_ratio: float
    soft_abs: int
    hard_ratio: float
    hard_abs: int
    keep_turns: int
    consecutive_fail_record: int
    consecutive_fail_escalate: int
    thinking: str
    bash_timeout_seconds: int
    max_steps: int
    bash_truncate_head: int
    bash_truncate_tail: int
    session_dir: str
    config_path: Path


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def find_agent_toml(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    candidates = [here / "agent.toml", * (p / "agent.toml" for p in here.parents)]
    repo_default = Path(__file__).resolve().parents[2] / "agent.toml"
    candidates.append(repo_default)
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("agent.toml not found")


def load_config(path: Path | None = None, *, cwd: Path | None = None) -> Config:
    cwd = (cwd or Path.cwd()).resolve()
    _load_dotenv(cwd / ".env")
    _load_dotenv(Path(__file__).resolve().parents[2] / ".env")

    config_path = path or find_agent_toml(cwd)
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))

    thinking = str(data.get("thinking", "enabled"))
    if thinking not in {"enabled", "disabled"}:
        raise ValueError(f"thinking must be enabled or disabled, got {thinking!r}")

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL") or str(
        data.get("base_url", "https://api.deepseek.com")
    )
    return Config(
        model=str(data.get("model", "deepseek-flash")),
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        context_window=int(data.get("context_window", 1_000_000)),
        soft_ratio=float(data.get("soft_ratio", 0.5)),
        soft_abs=int(data.get("soft_abs", 60_000)),
        hard_ratio=float(data.get("hard_ratio", 0.7)),
        hard_abs=int(data.get("hard_abs", 90_000)),
        keep_turns=int(data.get("keep_turns", 6)),
        consecutive_fail_record=int(data.get("consecutive_fail_record", 3)),
        consecutive_fail_escalate=int(data.get("consecutive_fail_escalate", 5)),
        thinking=thinking,
        bash_timeout_seconds=int(data.get("bash_timeout_seconds", 120)),
        max_steps=int(data.get("max_steps", 100)),
        bash_truncate_head=int(data.get("bash_truncate_head", 2000)),
        bash_truncate_tail=int(data.get("bash_truncate_tail", 2000)),
        session_dir=str(data.get("session_dir", ".agent/sessions")),
        config_path=config_path,
    )


def resolve_session_dir(config: Config, cwd: Path) -> Path:
    raw = Path(config.session_dir)
    if raw.is_absolute():
        return raw
    return cwd / raw
