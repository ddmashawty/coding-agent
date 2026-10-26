import json

from agent0.agent.messages import (
    SYSTEM_PROMPT,
    AssistantMessage,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    to_llm_messages,
)
from agent0.providers.base import build_chat_request, request_bytes
from agent0.tools.registry import default_tools, headless_tools


def _state_messages():
    return [
        SystemMessage(SYSTEM_PROMPT),
        UserMessage("read a then count lines"),
        AssistantMessage(
            content="",
            reasoning_content="I will read the file first.",
            tool_calls=[ToolCall("call_1", "read", '{"path":"a.txt"}')],
        ),
        ToolResultMessage("call_1", "read", "alpha"),
    ]


def test_request_prefix_stable_and_tool_order(config) -> None:
    tools = default_tools(config).schemas()
    messages = to_llm_messages(_state_messages())
    first = request_bytes(
        build_chat_request(
            model=config.model,
            messages=messages,
            tools=tools,
            thinking=config.thinking,
            stream=True,
        )
    )
    second = request_bytes(
        build_chat_request(
            model=config.model,
            messages=to_llm_messages(_state_messages()),
            tools=default_tools(config).schemas(),
            thinking=config.thinking,
            stream=True,
        )
    )
    assert first == second
    body = json.loads(first)
    assert [item["function"]["name"] for item in body["tools"]] == [
        "read",
        "write",
        "edit",
        "bash",
    ]
    assert "stream_options" in body
    assert body["stream_options"]["include_usage"] is True
    assert body["thinking"] == {"type": "enabled"}
    assert SYSTEM_PROMPT in body["messages"][0]["content"]
    assert "2026" not in SYSTEM_PROMPT
    assert "uuid" not in SYSTEM_PROMPT.lower()


def test_headless_tool_order(config) -> None:
    names = [item["function"]["name"] for item in headless_tools(config).schemas()]
    assert names == ["read", "write", "edit", "bash", "submit"]


def test_system_prompt_is_deterministic() -> None:
    assert SYSTEM_PROMPT == SYSTEM_PROMPT
    assert "{" not in SYSTEM_PROMPT
