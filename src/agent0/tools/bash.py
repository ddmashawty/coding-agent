from __future__ import annotations

import hashlib
from typing import Any

from agent0.executors.base import Executor
from agent0.tools.base import Tool


class BashTool(Tool):
    name = "bash"
    description = "Run a shell command in the working directory."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run."},
            "timeout": {
                "type": "number",
                "description": "Timeout in seconds. Defaults to the configured bash timeout.",
            },
        },
        "required": ["command"],
    }

    def __init__(
        self,
        *,
        default_timeout: int = 120,
        head_chars: int = 2000,
        tail_chars: int = 2000,
    ) -> None:
        self.default_timeout = default_timeout
        self.head_chars = head_chars
        self.tail_chars = tail_chars

    def run(self, executor: Executor, arguments: dict[str, Any]) -> str:
        command = arguments.get("command")
        if not isinstance(command, str) or not command:
            return "Error: command is required."
        timeout = arguments.get("timeout", self.default_timeout)
        try:
            timeout_s = float(timeout)
        except (TypeError, ValueError):
            return "Error: timeout must be a number."
        if timeout_s <= 0:
            return "Error: timeout must be positive."

        result = executor.run(command, timeout=timeout_s)
        combined = result.stdout
        if result.stderr:
            combined = combined + ("\n" if combined and not combined.endswith("\n") else "") + result.stderr
        if result.timed_out:
            header = f"Error: command timed out after {timeout_s} seconds.\nexit_code={result.exit_code}\n"
            body = combined
        else:
            header = f"exit_code={result.exit_code}\n"
            body = combined

        text = header + body
        limit = self.head_chars + self.tail_chars
        if len(text) <= limit:
            return text

        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        artifact = f".agent/artifacts/{digest}.txt"
        executor.write_text(artifact, text)
        return (
            f"{text[: self.head_chars]}\n"
            f"...[truncated {len(text) - limit} chars; full output at {artifact}]...\n"
            f"{text[-self.tail_chars :]}"
        )
