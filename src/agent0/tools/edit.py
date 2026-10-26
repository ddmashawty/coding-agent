from __future__ import annotations

import difflib
from typing import Any

from agent0.executors.base import Executor
from agent0.tools.base import Tool


class EditTool(Tool):
    name = "edit"
    description = (
        "Replace an exact string in a UTF-8 file. The old string must match exactly once. "
        "Returns a unified diff."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to edit."},
            "old_string": {"type": "string", "description": "Exact text to find."},
            "new_string": {"type": "string", "description": "Replacement text."},
        },
        "required": ["path", "old_string", "new_string"],
    }

    def run(self, executor: Executor, arguments: dict[str, Any]) -> str:
        path = arguments.get("path")
        old = arguments.get("old_string")
        new = arguments.get("new_string")
        if not isinstance(path, str) or not path:
            return "Error: path is required."
        if not isinstance(old, str) or not old:
            return "Error: old_string is required and must be non-empty."
        if not isinstance(new, str):
            return "Error: new_string must be a string."
        try:
            text = executor.read_text(path)
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except OSError as exc:
            return f"Error: cannot read {path}: {exc}"

        count = text.count(old)
        if count == 0:
            return "Error: old_string not found."
        if count > 1:
            return f"Error: old_string matched {count} times; match must be unique."

        updated = text.replace(old, new, 1)
        try:
            executor.write_text(path, updated)
        except OSError as exc:
            return f"Error: cannot write {path}: {exc}"

        diff = "".join(
            difflib.unified_diff(
                text.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=path,
                tofile=path,
            )
        )
        return diff if diff else f"edited {path} (no textual diff)"
