from __future__ import annotations

from agent0.agent.loop import TRUNCATED_NOTICE, AfterTurn, AgentLoop, BeforeTool, Hooks
from agent0.agent.messages import (
    SUBMIT_HINT,
    SYSTEM_PROMPT,
    AssistantMessage,
    InternalNote,
    SystemMessage,
    ToolResultMessage,
    to_llm_messages,
)
from agent0.providers.base import MissingReasoningContent, ProviderResponse, ToolCallRequest
from agent0.providers.fake import FakeProvider


def _loop(config, executor, tools, script, hooks=None, listeners=None) -> AgentLoop:
    return AgentLoop(
        config=config,
        provider=FakeProvider(script),
        executor=executor,
        tools=tools,
        hooks=hooks,
        listeners=listeners or [],
    )


def test_headless_system_prompt_requires_submit(config, executor) -> None:
    from agent0.tools.registry import default_tools, headless_tools

    interactive = _loop(config, executor, default_tools(config), [])
    assert interactive.messages[0].content == SYSTEM_PROMPT
    assert "submit" not in interactive.messages[0].content

    headless = _loop(config, executor, headless_tools(config), [])
    assert isinstance(headless.messages[0], SystemMessage)
    assert headless.messages[0].content == SYSTEM_PROMPT + SUBMIT_HINT
    assert "must call submit" in headless.messages[0].content


def test_text_only_turn(config, executor, tools, tmp_path) -> None:
    loop = _loop(
        config,
        executor,
        tools,
        [ProviderResponse("done", "r", [], "stop")],
    )
    assert loop.run("hello") == "done"
    roles = [type(m).__name__ for m in loop.messages]
    assert roles == ["SystemMessage", "UserMessage", "AssistantMessage"]


def test_read_then_answer(config, executor, tools, tmp_path) -> None:
    (tmp_path / "note.txt").write_text("secret-word", encoding="utf-8")
    loop = _loop(
        config,
        executor,
        tools,
        [
            ProviderResponse(
                "",
                "read it",
                [ToolCallRequest("c1", "read", '{"path":"note.txt"}')],
                "tool_calls",
            ),
            ProviderResponse("the file says secret-word", "answer", [], "stop"),
        ],
    )
    assert loop.run("what is in note.txt?") == "the file says secret-word"
    results = [m for m in loop.messages if isinstance(m, ToolResultMessage)]
    assert results[0].content == "secret-word"


def test_serial_read_then_bash(config, executor, tools, tmp_path) -> None:
    (tmp_path / "note.txt").write_text("abc\n", encoding="utf-8")
    order: list[str] = []

    def before(name: str, arguments: dict) -> BeforeTool:
        order.append(name)
        return BeforeTool(proceed=True, arguments=arguments)

    loop = _loop(
        config,
        executor,
        tools,
        [
            ProviderResponse(
                "",
                "both",
                [
                    ToolCallRequest("c1", "read", '{"path":"note.txt"}'),
                    ToolCallRequest("c2", "bash", '{"command":"printf ran"}'),
                ],
                "tool_calls",
            ),
            ProviderResponse("ok", "done", [], "stop"),
        ],
        hooks=Hooks(before_tool_call=before),
    )
    loop.run("do both")
    assert order == ["read", "bash"]
    results = [m for m in loop.messages if isinstance(m, ToolResultMessage)]
    assert [m.tool_call_id for m in results] == ["c1", "c2"]
    assert results[0].content == "abc\n"
    assert "ran" in results[1].content


def test_every_tool_call_has_result(config, executor, tools) -> None:
    loop = _loop(
        config,
        executor,
        tools,
        [
            ProviderResponse(
                "",
                "r",
                [
                    ToolCallRequest("a", "read", '{"path":"missing.txt"}'),
                    ToolCallRequest("b", "unknown_tool", "{}"),
                ],
                "tool_calls",
            ),
            ProviderResponse("ok", "r2", [], "stop"),
        ],
    )
    loop.run("go")
    calls = []
    results = []
    for message in loop.messages:
        if isinstance(message, AssistantMessage):
            calls.extend(call.id for call in message.tool_calls)
        if isinstance(message, ToolResultMessage):
            results.append(message.tool_call_id)
    assert calls == results == ["a", "b"]


def test_before_tool_can_block(config, executor, tools, tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hidden", encoding="utf-8")

    def before(name: str, arguments: dict) -> BeforeTool:
        return BeforeTool(proceed=False, arguments=arguments, error="Error: blocked by hook")

    loop = _loop(
        config,
        executor,
        tools,
        [
            ProviderResponse(
                "",
                "r",
                [ToolCallRequest("c1", "read", '{"path":"note.txt"}')],
                "tool_calls",
            ),
            ProviderResponse("blocked", "r2", [], "stop"),
        ],
        hooks=Hooks(before_tool_call=before),
    )
    loop.run("read it")
    result = next(m for m in loop.messages if isinstance(m, ToolResultMessage))
    assert "blocked" in result.content
    assert result.content != "hidden"


def test_transform_context_does_not_mutate_original(config, executor, tools) -> None:
    seen = {}

    def transform(messages):
        clone = list(messages)
        clone.append(InternalNote("tmp", "should not stick"))
        seen["len"] = len(messages)
        return clone

    loop = _loop(
        config,
        executor,
        tools,
        [ProviderResponse("ok", "r", [], "stop")],
        hooks=Hooks(transform_context=transform),
    )
    loop.run("hi")
    assert all(not isinstance(m, InternalNote) for m in loop.messages)
    assert seen["len"] == 2  # system + user at first call


class _SpyExecutor:
    def __init__(self, inner) -> None:
        self.inner = inner
        self.calls: list[tuple] = []

    def run(self, command: str, *, timeout: float):
        self.calls.append(("run", command))
        return self.inner.run(command, timeout=timeout)

    def read_text(self, path: str) -> str:
        self.calls.append(("read", path))
        return self.inner.read_text(path)

    def write_text(self, path: str, content: str) -> None:
        self.calls.append(("write", path))
        return self.inner.write_text(path, content)


def test_length_does_not_execute_tools(config, executor, tools, tmp_path) -> None:
    (tmp_path / "note.txt").write_text("should-not-read", encoding="utf-8")
    loop = _loop(
        config,
        executor,
        tools,
        [
            ProviderResponse(
                "partial",
                "r",
                [ToolCallRequest("c1", "read", '{"path":"note.txt"}')],
                "length",
            ),
            ProviderResponse("retried", "r2", [], "stop"),
        ],
    )
    loop.run("read note")
    assert not any(isinstance(m, ToolResultMessage) for m in loop.messages)
    assistant = [m for m in loop.messages if isinstance(m, AssistantMessage)][0]
    assert assistant.tool_calls == []
    assert any(isinstance(m, InternalNote) and m.kind == "truncated" for m in loop.messages)
    assert any(getattr(m, "content", "") == TRUNCATED_NOTICE for m in loop.messages)
    assert loop.messages[-1].content == "retried"


def test_length_with_multiple_tools_never_touches_executor(config, executor, tools, tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hidden", encoding="utf-8")
    spy = _SpyExecutor(executor)
    provider = FakeProvider(
        [
            ProviderResponse(
                "partial",
                "keep-this-reasoning",
                [
                    ToolCallRequest("c1", "read", '{"path":"note.txt"}'),
                    ToolCallRequest("c2", "bash", '{"command":"echo leaked"}'),
                ],
                "length",
            ),
            ProviderResponse("retried", "r2", [], "stop"),
        ]
    )
    loop = AgentLoop(config=config, provider=provider, executor=spy, tools=tools)
    loop.run("do both")
    assert spy.calls == []
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "hidden"
    second = provider.requests[1][0]
    assistant = next(item for item in second if item.get("role") == "assistant")
    assert assistant["reasoning_content"] == "keep-this-reasoning"
    assert "tool_calls" not in assistant
    assert any(item.get("content") == TRUNCATED_NOTICE for item in second)


def test_fake_provider_rejects_missing_reasoning(config, executor, tools) -> None:
    provider = FakeProvider([ProviderResponse("x", "r", [], "stop")])
    try:
        provider.complete(
            [{"role": "assistant", "content": "", "tool_calls": []}],
            tools.schemas(),
        )
    except MissingReasoningContent:
        return
    raise AssertionError("expected MissingReasoningContent")


def test_max_steps_counts_model_call_rounds(config, executor, tools) -> None:
    from dataclasses import replace

    cfg = replace(config, max_steps=2)
    loop = _loop(
        cfg,
        executor,
        tools,
        [
            ProviderResponse(
                "",
                "r1",
                [ToolCallRequest("c1", "read", '{"path":"missing.txt"}')],
                "tool_calls",
            ),
            ProviderResponse(
                "",
                "r2",
                [ToolCallRequest("c2", "read", '{"path":"missing.txt"}')],
                "tool_calls",
            ),
            ProviderResponse("should-not-run", "r3", [], "stop"),
        ],
    )
    loop.run("go")
    assert loop.steps == 2
    assert loop.max_steps_hit is True
    assert loop.submitted is False
    assistants = [m for m in loop.messages if isinstance(m, AssistantMessage)]
    assert len(assistants) == 2


def test_after_turn_can_stop(config, executor, tools) -> None:
    loop = _loop(
        config,
        executor,
        tools,
        [
            ProviderResponse(
                "",
                "r",
                [ToolCallRequest("c1", "read", '{"path":"missing.txt"}')],
                "tool_calls",
            ),
            ProviderResponse("should-not-run", "r2", [], "stop"),
        ],
        hooks=Hooks(after_turn=lambda _msgs: AfterTurn(stop=True)),
    )
    loop.run("go")
    assistants = [m for m in loop.messages if isinstance(m, AssistantMessage)]
    assert len(assistants) == 1


def test_second_request_echoes_reasoning(config, executor, tools, tmp_path) -> None:
    (tmp_path / "note.txt").write_text("z", encoding="utf-8")
    provider = FakeProvider(
        [
            ProviderResponse(
                "",
                "keep-me-exactly",
                [ToolCallRequest("c1", "read", '{"path":"note.txt"}')],
                "tool_calls",
            ),
            ProviderResponse("z", "r2", [], "stop"),
        ]
    )
    loop = AgentLoop(config=config, provider=provider, executor=executor, tools=tools)
    loop.run("go")
    assert len(provider.requests) == 2
    second_messages = provider.requests[1][0]
    assistant = next(m for m in second_messages if m.get("role") == "assistant")
    assert assistant["reasoning_content"] == "keep-me-exactly"
    leaked = to_llm_messages(loop.messages)
    assert all("InternalNote" not in str(item) for item in leaked)
