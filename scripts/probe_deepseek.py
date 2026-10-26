#!/usr/bin/env python3
"""Print raw DeepSeek responses (stream / non-stream, with and without tools).

Saves redacted fixtures under tests/fixtures/deepseek/.
Requires DEEPSEEK_API_KEY. Does not import the agent parser.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent0.config import load_config  # noqa: E402
from agent0.providers.base import build_chat_request  # noqa: E402
from agent0.redact import redact_secrets  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "deepseek"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read a UTF-8 text file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }
]


def _redact(text: str, api_key: str) -> str:
    return redact_secrets(text, api_key)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")


def _post_json(client: httpx.Client, url: str, headers: dict[str, str], body: dict) -> httpx.Response:
    return client.post(url, headers=headers, json=body)


def main() -> int:
    config = load_config()
    if not config.api_key:
        print("DEEPSEEK_API_KEY is not set", file=sys.stderr)
        return 2

    url = f"{config.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    cases = [
        (
            "nonstream_text",
            False,
            None,
            [{"role": "user", "content": "Reply with exactly the word pong."}],
        ),
        (
            "stream_text",
            True,
            None,
            [{"role": "user", "content": "Reply with exactly the word pong."}],
        ),
        (
            "nonstream_tools",
            False,
            TOOLS,
            [
                {
                    "role": "user",
                    "content": "Call the read tool on path probe.txt. Do not answer without the tool.",
                }
            ],
        ),
        (
            "stream_tools",
            True,
            TOOLS,
            [
                {
                    "role": "user",
                    "content": "Call the read tool on path probe.txt. Do not answer without the tool.",
                }
            ],
        ),
    ]

    notes: dict[str, object] = {"model": config.model, "thinking": config.thinking, "cases": {}}

    with httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
        for name, stream, tools, messages in cases:
            body = build_chat_request(
                model=config.model,
                messages=messages,
                tools=tools,
                thinking=config.thinking,
                stream=stream,
            )
            print(f"\n=== {name} ===")
            print("request:", _redact(json.dumps(body, ensure_ascii=False), config.api_key))
            if stream:
                raw_lines: list[str] = []
                with client.stream("POST", url, headers=headers, json=body) as response:
                    print(f"HTTP {response.status_code}")
                    if response.status_code >= 400:
                        err = _redact(response.read().decode("utf-8", errors="replace"), config.api_key)
                        print(err)
                        notes["cases"][name] = {"http": response.status_code, "error": True}
                        continue
                    for line in response.iter_lines():
                        if line is None:
                            continue
                        raw_lines.append(line)
                        print(_redact(line, config.api_key))
                text = "\n".join(raw_lines) + "\n"
                _write(FIXTURE_DIR / f"{name}.sse", _redact(text, config.api_key))
                usage_only = 0
                usage_on_content = 0
                for line in raw_lines:
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("usage") and not chunk.get("choices"):
                        usage_only += 1
                    if chunk.get("usage") and chunk.get("choices"):
                        usage_on_content += 1
                notes["cases"][name] = {
                    "http": 200,
                    "usage_only_chunks": usage_only,
                    "usage_on_content_chunks": usage_on_content,
                }
            else:
                response = _post_json(client, url, headers, body)
                text = _redact(response.text, config.api_key)
                print(f"HTTP {response.status_code}")
                print(text)
                notes["cases"][name] = {"http": response.status_code}
                if response.status_code >= 400:
                    notes["cases"][name]["error"] = True
                    continue
                _write(FIXTURE_DIR / f"{name}.json", text if text.endswith("\n") else text + "\n")

    _write(FIXTURE_DIR / "probe_notes.json", json.dumps(notes, ensure_ascii=False, indent=2) + "\n")
    failed = [name for name, info in notes["cases"].items() if info.get("error") or info.get("http") != 200]
    if failed:
        print("probe failed:", ", ".join(failed), file=sys.stderr)
        return 1
    compare_truncation(client=None, config=config, url=url, headers=headers)
    return 0


def compare_truncation(*, client: httpx.Client | None, config, url: str, headers: dict[str, str]) -> None:
    fixture_path = FIXTURE_DIR / "nonstream_tools.json"
    if not fixture_path.is_file():
        print("skip truncation compare: missing nonstream_tools.json", file=sys.stderr)
        return
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    try:
        message = payload["choices"][0]["message"]
        tool_calls = message["tool_calls"]
        tool_id = tool_calls[0]["id"]
    except (KeyError, IndexError, TypeError):
        print("skip truncation compare: fixture has no tool_calls", file=sys.stderr)
        return

    user = {
        "role": "user",
        "content": "Call the read tool on path probe.txt. Do not answer without the tool.",
    }
    notice = (
        "Error: previous model response was truncated (finish_reason=length). "
        "Tool calls in that response were not executed. Reply again."
    )
    assistant_drop = {
        "role": "assistant",
        "content": message.get("content") or "",
        "reasoning_content": message.get("reasoning_content") or "",
    }
    assistant_keep = {
        "role": "assistant",
        "content": message.get("content") or "",
        "reasoning_content": message.get("reasoning_content") or "",
        "tool_calls": [
            {
                "id": item.get("id"),
                "type": item.get("type", "function"),
                "function": item.get("function"),
            }
            for item in tool_calls
        ],
    }
    strategies = {
        "drop_tool_calls": [user, assistant_drop, {"role": "user", "content": notice}],
        "keep_tool_calls_with_error_result": [
            user,
            assistant_keep,
            {"role": "tool", "tool_call_id": tool_id, "content": notice},
        ],
    }
    results: dict[str, object] = {}
    owns = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0))
    try:
        for name, messages in strategies.items():
            body = build_chat_request(
                model=config.model,
                messages=messages,
                tools=TOOLS,
                thinking=config.thinking,
                stream=False,
            )
            print(f"\n=== truncation_{name} ===")
            response = http.post(url, headers=headers, json=body)
            text = _redact(response.text, config.api_key)
            print(f"HTTP {response.status_code}")
            print(text)
            results[name] = {"http": response.status_code, "body": json.loads(text) if text.startswith("{") else text}
    finally:
        if owns:
            http.close()
    _write(FIXTURE_DIR / "truncation_compare.json", json.dumps(results, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
