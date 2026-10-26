from agent0.agent.messages import (
    AssistantMessage,
    InternalNote,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    to_llm_messages,
    to_record,
)


def test_custom_types_do_not_leak() -> None:
    messages = [
        SystemMessage("sys"),
        UserMessage("hi"),
        InternalNote("debug", "secret harness note"),
        AssistantMessage(content="ok", reasoning_content="think"),
    ]
    llm = to_llm_messages(messages)
    assert [item["role"] for item in llm] == ["system", "user", "assistant"]
    dumped = str(llm)
    assert "secret harness note" not in dumped
    assert "internal" not in dumped


def test_reasoning_content_roundtrip_verbatim() -> None:
    text = "keep every rune 字 for 字\nincluding trailing spaces  "
    message = AssistantMessage(
        content="hi",
        reasoning_content=text,
        tool_calls=[ToolCall(id="call_1", name="read", arguments='{"path":"a"}')],
    )
    llm = to_llm_messages([message])
    assert llm[0]["reasoning_content"] == text
    record = to_record(message)
    assert record["reasoning_content"] == text


def test_tool_result_order_preserved() -> None:
    messages = [
        AssistantMessage(
            reasoning_content="r",
            tool_calls=[
                ToolCall("c1", "read", "{}"),
                ToolCall("c2", "bash", "{}"),
            ],
        ),
        ToolResultMessage("c1", "read", "A"),
        ToolResultMessage("c2", "bash", "B"),
    ]
    llm = to_llm_messages(messages)
    assert llm[1]["tool_call_id"] == "c1"
    assert llm[2]["tool_call_id"] == "c2"
