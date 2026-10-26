from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from agent0.providers.base import (
    Provider,
    ProviderResponse,
    StreamDelta,
    require_reasoning_content,
)


class FakeProvider(Provider):
    """Scripted provider. Never touches the network."""

    def __init__(self, script: Iterable[ProviderResponse]) -> None:
        self._script = list(script)
        self.requests: list[tuple[list[dict[str, Any]], list[dict[str, Any]] | None]] = []

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> Iterator[StreamDelta]:
        require_reasoning_content(messages, tools)
        self.requests.append((messages, tools))
        if not self._script:
            raise RuntimeError("fake provider script exhausted")
        response = self._script.pop(0)
        if response.reasoning_content:
            yield StreamDelta(reasoning=response.reasoning_content)
        if response.content:
            yield StreamDelta(text=response.content)
        yield StreamDelta(done=True, response=response)
