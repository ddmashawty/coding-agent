from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent0.providers.deepseek import parse_nonstream, parse_stream_sse

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "deepseek"


def _require(*names: str) -> None:
    missing = [name for name in names if not (FIXTURE_DIR / name).is_file()]
    if missing:
        pytest.fail(
            "missing DeepSeek fixtures: "
            + ", ".join(missing)
            + ". Run: uv run python scripts/probe_deepseek.py"
        )


def test_nonstream_text_keeps_raw_usage() -> None:
    _require("nonstream_text.json")
    payload = json.loads((FIXTURE_DIR / "nonstream_text.json").read_text(encoding="utf-8"))
    parsed = parse_nonstream(payload)
    assert parsed.usage is not None
    raw = parsed.usage.raw
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
    ):
        assert key in raw
    assert parsed.usage.prompt_tokens == raw["prompt_tokens"]
    assert parsed.usage.completion_tokens == raw["completion_tokens"]
    assert parsed.usage.prompt_cache_hit_tokens == raw["prompt_cache_hit_tokens"]
    assert parsed.usage.prompt_cache_miss_tokens == raw["prompt_cache_miss_tokens"]
    assert parsed.finish_reason
    assert parsed.content


def test_stream_text_reads_usage_from_trailing_chunk() -> None:
    _require("stream_text.sse")
    lines = (FIXTURE_DIR / "stream_text.sse").read_text(encoding="utf-8").splitlines()
    parsed = parse_stream_sse(lines)
    assert parsed.usage is not None
    raw = parsed.usage.raw
    assert "prompt_cache_hit_tokens" in raw
    assert "prompt_cache_miss_tokens" in raw
    assert parsed.content


def test_nonstream_tools_parses_tool_calls() -> None:
    _require("nonstream_tools.json")
    payload = json.loads((FIXTURE_DIR / "nonstream_tools.json").read_text(encoding="utf-8"))
    parsed = parse_nonstream(payload)
    assert parsed.finish_reason in {"tool_calls", "stop"}
    if parsed.finish_reason == "tool_calls":
        assert parsed.tool_calls
        assert parsed.tool_calls[0].name == "read"
        assert isinstance(parsed.reasoning_content, str)


def test_stream_tools_parses_tool_calls() -> None:
    _require("stream_tools.sse")
    lines = (FIXTURE_DIR / "stream_tools.sse").read_text(encoding="utf-8").splitlines()
    parsed = parse_stream_sse(lines)
    assert parsed.usage is not None
    if parsed.finish_reason == "tool_calls":
        assert parsed.tool_calls
        assert parsed.tool_calls[0].name
        assert isinstance(parsed.reasoning_content, str)
