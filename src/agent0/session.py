from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from agent0.agent.messages import (
    INTERRUPTED_TOOL,
    AssistantMessage,
    Message,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    from_record,
    to_record,
)
from agent0.redact import redact_obj


class Session:
    """Append-only JSONL. Never rewrite or delete existing lines."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.warnings: list[str] = []
        self._next_id = 1
        self._parent_id: str | None = None

    @property
    def session_id(self) -> str:
        return self.path.stem

    @classmethod
    def create(cls, directory: Path, session_id: str | None = None) -> Session:
        directory.mkdir(parents=True, exist_ok=True)
        sid = session_id or uuid.uuid4().hex
        path = directory / f"{sid}.jsonl"
        path.touch()
        return cls(path)

    @classmethod
    def is_session_file(cls, path: Path) -> bool:
        """True for <id>.jsonl. Sidecar event logs are <id>.events.jsonl."""
        return path.is_file() and path.suffix == ".jsonl" and not path.name.endswith(".events.jsonl")

    @classmethod
    def latest_path(cls, directory: Path) -> Path | None:
        if not directory.is_dir():
            return None
        files = [path for path in directory.glob("*.jsonl") if cls.is_session_file(path)]
        if not files:
            return None
        return max(files, key=lambda path: path.stat().st_mtime)

    @classmethod
    def open_latest(cls, directory: Path) -> Session:
        path = cls.latest_path(directory)
        if path is None:
            raise FileNotFoundError(f"no sessions in {directory}")
        return cls(path)

    def append(self, message: Message, *, api_key: str = "") -> dict:
        body = redact_obj(to_record(message), api_key)
        if not isinstance(body, dict):
            raise TypeError("redacted record must be a dict")
        record = {"id": str(self._next_id), "parent_id": self._parent_id, **body}
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        self._parent_id = record["id"]
        self._next_id += 1
        return record

    def load(self) -> list[Message]:
        self.warnings.clear()
        if not self.path.is_file():
            return []
        text = self.path.read_text(encoding="utf-8")
        if not text:
            return []
        lines = text.splitlines()
        messages: list[Message] = []
        records: list[dict] = []
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                if index == len(lines) - 1:
                    self.warnings.append("ignored truncated last JSONL line")
                    continue
                raise
            records.append(record)
            messages.append(from_record(record))
        if records:
            numeric = []
            for record in records:
                try:
                    numeric.append(int(record["id"]))
                except (KeyError, TypeError, ValueError):
                    continue
            if numeric:
                self._next_id = max(numeric) + 1
            self._parent_id = str(records[-1].get("id"))
        return messages

    def load_and_repair(self, *, api_key: str = "") -> list[Message]:
        messages = self.load()
        for result in unanswered_tool_results(messages):
            messages.append(result)
            self.append(result, api_key=api_key)
        return messages


def unanswered_tool_results(messages: list[Message]) -> list[ToolResultMessage]:
    pending: list[ToolCall] = []
    answered: set[str] = set()
    for message in messages:
        if isinstance(message, AssistantMessage) and message.tool_calls:
            pending = list(message.tool_calls)
            answered = set()
        elif isinstance(message, ToolResultMessage):
            answered.add(message.tool_call_id)
        elif isinstance(message, (UserMessage, SystemMessage)):
            pending = []
            answered = set()
    return [
        ToolResultMessage(call.id, call.name, INTERRUPTED_TOOL)
        for call in pending
        if call.id not in answered
    ]
