from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agent0.agent.messages import (
    SUBMIT_HINT,
    SYSTEM_PROMPT,
    AssistantMessage,
    InternalNote,
    Message,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    to_llm_messages,
)
from agent0.config import Config
from agent0.executors.base import Executor
from agent0.providers.base import Provider, ProviderResponse, StreamDelta
from agent0.redact import redact_obj
from agent0.session import Session
from agent0.tools.base import ToolRegistry

EVENT_AGENT_START = "agent_start"
EVENT_TURN_START = "turn_start"
EVENT_MESSAGE_START = "message_start"
EVENT_MESSAGE_END = "message_end"
EVENT_TOOL_START = "tool_execution_start"
EVENT_TOOL_END = "tool_execution_end"
EVENT_TURN_END = "turn_end"
EVENT_AGENT_END = "agent_end"

TRUNCATED_NOTICE = (
    "Error: previous model response was truncated (finish_reason=length). "
    "Tool calls in that response were not executed. Reply again."
)

Listener = Callable[[str, dict[str, Any]], None]


@dataclass
class BeforeTool:
    proceed: bool = True
    arguments: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class AfterTurn:
    stop: bool = False
    replace_context: list[Message] | None = None


@dataclass
class Hooks:
    transform_context: Callable[[list[Message]], list[Message]] | None = None
    before_tool_call: Callable[[str, dict[str, Any]], BeforeTool] | None = None
    after_tool_call: Callable[[str, dict[str, Any], str], str] | None = None
    after_turn: Callable[[list[Message]], AfterTurn] | None = None


class AgentLoop:
    def __init__(
        self,
        *,
        config: Config,
        provider: Provider,
        executor: Executor,
        tools: ToolRegistry,
        hooks: Hooks | None = None,
        listeners: list[Listener] | None = None,
        on_delta: Callable[[StreamDelta], None] | None = None,
        session: Session | None = None,
        messages: list[Message] | None = None,
    ) -> None:
        self.config = config
        self.provider = provider
        self.executor = executor
        self.tools = tools
        self.hooks = hooks or Hooks()
        self.listeners = listeners or []
        self.on_delta = on_delta
        self.session = session
        self.messages: list[Message] = []
        self._steering: list[str] = []
        self.steps = 0
        self.submitted = False
        self.max_steps_hit = False
        if messages is None:
            prompt = SYSTEM_PROMPT
            if "submit" in tools.names():
                prompt = SYSTEM_PROMPT + SUBMIT_HINT
            self._add(SystemMessage(prompt))
        else:
            self.messages = list(messages)

    def steer(self, text: str) -> None:
        self._steering.append(text)

    def submit_followup(self, text: str) -> None:
        raise NotImplementedError("follow-up queue is not implemented in v0")

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        safe = redact_obj(payload or {}, self.config.api_key)
        if not isinstance(safe, dict):
            safe = {}
        for listener in self.listeners:
            listener(event_type, safe)

    def _add(self, message: Message) -> None:
        self.messages.append(message)
        if self.session is not None:
            self.session.append(message, api_key=self.config.api_key)

    def run(self, user_text: str, *, start_payload: dict[str, Any] | None = None) -> str:
        self._add(UserMessage(user_text))
        payload = {"task": user_text, **(start_payload or {})}
        self.emit(EVENT_AGENT_START, payload)
        error: BaseException | None = None
        final = ""
        try:
            final = self._inner()
        except BaseException as exc:
            error = exc
            raise
        finally:
            end_payload: dict[str, Any] = {
                "submitted": self.submitted,
                "max_steps_hit": self.max_steps_hit,
                "steps": self.steps,
            }
            if error is not None:
                redacted = redact_obj(str(error), self.config.api_key)
                end_payload["error"] = redacted if isinstance(redacted, str) else str(error)
            self.emit(EVENT_AGENT_END, end_payload)
        return final

    def _inner(self) -> str:
        final = ""
        stopped_early = False
        # max_steps is model-call rounds: one provider call per iteration.
        for step in range(self.config.max_steps):
            self.steps = step + 1
            for steered in self._steering:
                self._add(UserMessage(steered))
            self._steering.clear()

            self.emit(EVENT_TURN_START, {"step": step})
            view = list(self.messages)
            if self.hooks.transform_context is not None:
                view = self.hooks.transform_context(view)
            llm_messages = to_llm_messages(view, include_reasoning=True)
            tool_schemas = self.tools.schemas()

            self.emit(EVENT_MESSAGE_START, {"step": step})
            response = self._call_model(llm_messages, tool_schemas)
            self.emit(
                EVENT_MESSAGE_END,
                {
                    "finish_reason": response.finish_reason,
                    "usage": response.usage.raw if response.usage else None,
                },
            )

            if response.finish_reason == "length":
                self._add(
                    AssistantMessage(
                        content=response.content,
                        reasoning_content=response.reasoning_content,
                    )
                )
                self._add(InternalNote("truncated", TRUNCATED_NOTICE))
                self._add(UserMessage(TRUNCATED_NOTICE))
                final = TRUNCATED_NOTICE
                after = self._after_turn()
                if after.stop:
                    stopped_early = True
                    break
                continue

            assistant = AssistantMessage(
                content=response.content,
                reasoning_content=response.reasoning_content,
                tool_calls=[
                    ToolCall(id=call.id, name=call.name, arguments=call.arguments)
                    for call in response.tool_calls
                ],
            )
            self._add(assistant)
            final = response.content

            if not response.tool_calls:
                after = self._after_turn()
                self.emit(EVENT_TURN_END, {"step": step, "stop": True})
                stopped_early = True
                break
            stop_all = self._run_tools(response)
            if stop_all:
                self.submitted = True
                terminated = [
                    message
                    for message in self.messages
                    if isinstance(message, ToolResultMessage) and message.terminate
                ]
                if terminated:
                    final = terminated[-1].content
            after = self._after_turn()
            self.emit(EVENT_TURN_END, {"step": step, "stop": stop_all or after.stop})
            if stop_all or after.stop:
                stopped_early = True
                break
        if not stopped_early:
            self.max_steps_hit = True
        return final

    def _call_model(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ProviderResponse:
        final: ProviderResponse | None = None
        for delta in self.provider.stream(messages, tools):
            if self.on_delta is not None:
                self.on_delta(delta)
            if delta.done and delta.response is not None:
                final = delta.response
        if final is None:
            raise RuntimeError("provider returned no response")
        return final

    def _run_tools(self, response: ProviderResponse) -> bool:
        results: list[ToolResultMessage] = []
        for call in response.tool_calls:
            try:
                arguments = json.loads(call.arguments or "{}")
                if not isinstance(arguments, dict):
                    arguments = {"_": arguments}
            except json.JSONDecodeError:
                arguments = {}
                result_text = f"Error: invalid JSON arguments: {call.arguments}"
                result = ToolResultMessage(call.id, call.name, result_text)
                self._add(result)
                results.append(result)
                continue

            if self.hooks.before_tool_call is not None:
                decision = self.hooks.before_tool_call(call.name, arguments)
                if not decision.proceed:
                    result_text = decision.error or f"Error: tool {call.name} blocked."
                    result = ToolResultMessage(call.id, call.name, result_text)
                    self._add(result)
                    results.append(result)
                    continue
                arguments = decision.arguments or arguments

            self.emit(EVENT_TOOL_START, {"name": call.name, "arguments": arguments})
            terminate = False
            try:
                tool = self.tools.get(call.name)
            except KeyError:
                result_text = f"Error: unknown tool {call.name}"
            else:
                terminate = bool(tool.terminate)
                result_text = tool.run(self.executor, arguments)
            if self.hooks.after_tool_call is not None:
                result_text = self.hooks.after_tool_call(call.name, arguments, result_text)
            result = ToolResultMessage(call.id, call.name, result_text, terminate=terminate)
            self._add(result)
            results.append(result)
            self.emit(EVENT_TOOL_END, {"name": call.name, "result": result_text})

        return bool(results) and all(item.terminate for item in results)

    def _after_turn(self) -> AfterTurn:
        if self.hooks.after_turn is None:
            return AfterTurn()
        decision = self.hooks.after_turn(self.messages)
        if decision.replace_context is not None:
            self.messages = decision.replace_context
        return decision
