from __future__ import annotations

from typing import Any

from agent0.executors.base import Executor
from agent0.tools.base import Tool


class ReadTool(Tool):
    name = "read"
    description = "Read a UTF-8 text file relative to the working directory."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to read."},
        },
        "required": ["path"],
    }

    def run(self, executor: Executor, arguments: dict[str, Any]) -> str:
        path = arguments.get("path")
        if not isinstance(path, str) or not path:
            return "Error: path is required."
        try:
            return executor.read_text(path)
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except IsADirectoryError:
            return f"Error: path is a directory: {path}"
        except UnicodeDecodeError:
            return f"Error: not a UTF-8 text file: {path}"
        except OSError as exc:
            return f"Error: cannot read {path}: {exc}"
