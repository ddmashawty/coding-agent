from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


class MissingReasoningContent(ValueError):
    """Raised when a tools request is missing reasoning_content on an assistant turn."""


@dataclass
class Usage:
    raw: dict[str, Any]

    @property
    def prompt_tokens(self) -> int:
        return int(self.raw.get("prompt_tokens") or 0)

    @property
    def completion_tokens(self) -> int:
        return int(self.raw.get("completion_tokens") or 0)

    @property
    def prompt_cache_hit_tokens(self) -> int:
        return int(self.raw.get("prompt_cache_hit_tokens") or 0)

    @property
    def prompt_cache_miss_tokens(self) -> int:
        return int(self.raw.get("prompt_cache_miss_tokens") or 0)


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: str


@dataclass
class ProviderResponse:
    content: str
    reasoning_content: str
    tool_calls: list[ToolCallRequest]
    finish_reason: str
    usage: Usage | None = None


@dataclass
class StreamDelta:
    text: str = ""
    reasoning: str = ""
    done: bool = False
    response: ProviderResponse | None = None


def build_chat_request(
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    thinking: str,
    stream: bool,
) -> dict[str, Any]:
    # Insertion order is part of the cache prefix. Do not shuffle keys or tools.
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if tools:
        body["tools"] = tools
    body["thinking"] = {"type": thinking}
    body["stream"] = stream
    if stream:
        body["stream_options"] = {"include_usage": True}
    return body


def request_bytes(body: dict[str, Any]) -> bytes:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def require_reasoning_content(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> None:
    if not tools:
        return
    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        if "reasoning_content" not in message:
            raise MissingReasoningContent(
                f"assistant message at index {index} missing reasoning_content"
            )


class Provider(ABC):
    @abstractmethod
    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> Iterator[StreamDelta]:
        raise NotImplementedError

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> ProviderResponse:
        final: ProviderResponse | None = None
        for delta in self.stream(messages, tools):
            if delta.done and delta.response is not None:
                final = delta.response
        if final is None:
            raise RuntimeError("provider stream ended without a response")
        return final
