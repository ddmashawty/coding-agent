from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Union

# Fixed text. No clock, no randomness — request prefixes must stay stable.
SYSTEM_PROMPT = """You are agent0, a local coding agent.
Use tools only when they help. Tools run one at a time, in the order you emit them.
Available tools: read (UTF-8 file), write (create or overwrite a UTF-8 file), edit (exact unique string replace, returns a diff), bash (shell command).
If a tool fails, read the error and try another approach. Prefer facts from tools over guesses.
"""

SUBMIT_HINT = (
    "submit is available. You must call submit when the task is finished; "
    "the run does not end until you do.\n"
)

INTERRUPTED_TOOL = "会话在执行前中断，工具未执行"


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class SystemMessage:
    content: str


@dataclass
class UserMessage:
    content: str


@dataclass
class AssistantMessage:
    content: str = ""
    reasoning_content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class ToolResultMessage:
    tool_call_id: str
    name: str
    content: str
    terminate: bool = False


@dataclass
class InternalNote:
    """Custom harness message. Must never enter an LLM request."""

    kind: str
    payload: str


Message = Union[
    SystemMessage, UserMessage, AssistantMessage, ToolResultMessage, InternalNote
]


def to_llm_messages(
    messages: list[Message], *, include_reasoning: bool = True
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, InternalNote):
            continue
        if isinstance(message, SystemMessage):
            out.append({"role": "system", "content": message.content})
            continue
        if isinstance(message, UserMessage):
            out.append({"role": "user", "content": message.content})
            continue
        if isinstance(message, AssistantMessage):
            item: dict[str, Any] = {"role": "assistant", "content": message.content}
            if include_reasoning:
                item["reasoning_content"] = message.reasoning_content
            if message.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": call.arguments,
                        },
                    }
                    for call in message.tool_calls
                ]
            out.append(item)
            continue
        if isinstance(message, ToolResultMessage):
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content,
                }
            )
            continue
        raise TypeError(f"unknown message type: {type(message)!r}")
    return out


def to_record(message: Message) -> dict[str, Any]:
    """JSONL-ready dict. reasoning_content is kept verbatim."""
    if isinstance(message, SystemMessage):
        return {"type": "system", "content": message.content}
    if isinstance(message, UserMessage):
        return {"type": "user", "content": message.content}
    if isinstance(message, AssistantMessage):
        return {
            "type": "assistant",
            "content": message.content,
            "reasoning_content": message.reasoning_content,
            "tool_calls": [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in message.tool_calls
            ],
        }
    if isinstance(message, ToolResultMessage):
        return {
            "type": "tool",
            "tool_call_id": message.tool_call_id,
            "name": message.name,
            "content": message.content,
            "terminate": message.terminate,
        }
    if isinstance(message, InternalNote):
        return {"type": "internal", "kind": message.kind, "payload": message.payload}
    raise TypeError(f"unknown message type: {type(message)!r}")


def from_record(record: dict[str, Any]) -> Message:
    kind = record.get("type")
    if kind == "system":
        return SystemMessage(content=record.get("content") or "")
    if kind == "user":
        return UserMessage(content=record.get("content") or "")
    if kind == "assistant":
        calls = []
        for item in record.get("tool_calls") or []:
            calls.append(
                ToolCall(
                    id=item.get("id") or "",
                    name=item.get("name") or "",
                    arguments=item.get("arguments") or "",
                )
            )
        return AssistantMessage(
            content=record.get("content") or "",
            reasoning_content=record.get("reasoning_content") or "",
            tool_calls=calls,
        )
    if kind == "tool":
        return ToolResultMessage(
            tool_call_id=record.get("tool_call_id") or "",
            name=record.get("name") or "",
            content=record.get("content") or "",
            terminate=bool(record.get("terminate")),
        )
    if kind == "internal":
        return InternalNote(kind=record.get("kind") or "", payload=record.get("payload") or "")
    raise ValueError(f"unknown record type: {kind!r}")
