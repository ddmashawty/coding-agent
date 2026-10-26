from __future__ import annotations

from typing import Any

from agent0.executors.base import Executor
from agent0.tools.base import Tool


class SubmitTool(Tool):
    name = "submit"
    description = "Finish the headless run. Call when the task is complete."
    terminate = True
    parameters = {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Short summary of what was done.",
            }
        },
    }

    def run(self, executor: Executor, arguments: dict[str, Any]) -> str:
        summary = arguments.get("summary")
        if isinstance(summary, str) and summary:
            return summary
        return "submitted"
