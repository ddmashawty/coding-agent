from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from agent0.config import Config
from agent0.providers.base import (
    Provider,
    ProviderResponse,
    StreamDelta,
    ToolCallRequest,
    Usage,
    build_chat_request,
    require_reasoning_content,
)
from agent0.redact import redact_secrets


class DeepSeekError(RuntimeError):
    pass


def parse_nonstream(payload: dict[str, Any]) -> ProviderResponse:
    choices = payload.get("choices") or []
    if not choices:
        raise DeepSeekError("non-stream response has no choices")
    message = choices[0].get("message") or {}
    finish_reason = choices[0].get("finish_reason") or ""
    usage_raw = payload.get("usage")
    return ProviderResponse(
        content=message.get("content") or "",
        reasoning_content=message.get("reasoning_content") or "",
        tool_calls=_tool_calls_from_message(message.get("tool_calls")),
        finish_reason=finish_reason,
        usage=Usage(dict(usage_raw)) if isinstance(usage_raw, dict) else None,
    )


def parse_stream_sse(lines: list[str]) -> ProviderResponse:
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_acc: dict[int, dict[str, str]] = {}
    finish_reason = ""
    usage_raw: dict[str, Any] | None = None

    for raw in lines:
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        usage = chunk.get("usage")
        if isinstance(usage, dict):
            usage_raw = usage
        choices = chunk.get("choices") or []
        if not choices:
            # Trailing usage-only chunk: choices is an empty array.
            continue
        choice = choices[0]
        if choice.get("finish_reason"):
            finish_reason = choice["finish_reason"]
        delta = choice.get("delta") or {}
        if delta.get("content"):
            content_parts.append(delta["content"])
        if delta.get("reasoning_content"):
            reasoning_parts.append(delta["reasoning_content"])
        for item in delta.get("tool_calls") or []:
            index = int(item.get("index") or 0)
            acc = tool_acc.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if item.get("id"):
                acc["id"] = item["id"]
            function = item.get("function") or {}
            if function.get("name"):
                acc["name"] += function["name"]
            if function.get("arguments"):
                acc["arguments"] += function["arguments"]

    tool_calls = [
        ToolCallRequest(id=acc["id"], name=acc["name"], arguments=acc["arguments"])
        for _, acc in sorted(tool_acc.items())
    ]
    return ProviderResponse(
        content="".join(content_parts),
        reasoning_content="".join(reasoning_parts),
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=Usage(usage_raw) if usage_raw is not None else None,
    )


def _tool_calls_from_message(raw: object) -> list[ToolCallRequest]:
    if not raw:
        return []
    out: list[ToolCallRequest] = []
    for item in raw:
        function = item.get("function") or {}
        out.append(
            ToolCallRequest(
                id=item.get("id") or "",
                name=function.get("name") or "",
                arguments=function.get("arguments") or "",
            )
        )
    return out


class DeepSeekProvider(Provider):
    def __init__(self, config: Config, *, client: httpx.Client | None = None) -> None:
        self.config = config
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> Iterator[StreamDelta]:
        require_reasoning_content(messages, tools)
        if not self.config.api_key:
            raise DeepSeekError("DEEPSEEK_API_KEY is not set")
        body = build_chat_request(
            model=self.config.model,
            messages=messages,
            tools=tools,
            thinking=self.config.thinking,
            stream=True,
        )
        client = self._client or httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0))
        owns_client = self._client is None
        try:
            with client.stream(
                "POST",
                f"{self.config.base_url}/chat/completions",
                headers=self._headers(),
                json=body,
            ) as response:
                if response.status_code >= 400:
                    text = redact_secrets(response.read().decode("utf-8", errors="replace"), self.config.api_key)
                    raise DeepSeekError(f"DeepSeek HTTP {response.status_code}: {text}")
                raw_lines: list[str] = []
                for line in response.iter_lines():
                    if line is None:
                        continue
                    raw_lines.append(line)
                    stripped = line.strip()
                    if not stripped.startswith("data:"):
                        continue
                    data = stripped[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    if delta.get("reasoning_content"):
                        yield StreamDelta(reasoning=delta["reasoning_content"])
                    if delta.get("content"):
                        yield StreamDelta(text=delta["content"])
                parsed = parse_stream_sse(raw_lines)
                yield StreamDelta(done=True, response=parsed)
        finally:
            if owns_client:
                client.close()
