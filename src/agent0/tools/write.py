from __future__ import annotations

from typing import Any

from agent0.executors.base import Executor
from agent0.tools.base import Tool


class WriteTool(Tool):
    name = "write"
    description = "Create or overwrite a UTF-8 text file relative to the working directory."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to write."},
            "content": {"type": "string", "description": "Full file contents."},
        },
        "required": ["path", "content"],
    }

    def run(self, executor: Executor, arguments: dict[str, Any]) -> str:
        path = arguments.get("path")
        if not isinstance(path, str) or not path:
            return "Error: path is required."
        content = arguments.get("content")
        if not isinstance(content, str):
            return "Error: content must be a string."
        try:
            executor.write_text(path, content)
        except OSError as exc:
            return f"Error: cannot write {path}: {exc}"
        return f"wrote {path} ({len(content)} chars)"
