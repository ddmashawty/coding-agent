from agent0.config import Config
from agent0.tools.base import ToolRegistry
from agent0.tools.bash import BashTool
from agent0.tools.edit import EditTool
from agent0.tools.read import ReadTool
from agent0.tools.submit import SubmitTool
from agent0.tools.write import WriteTool


def _core_tools(config: Config) -> list:
    return [
        ReadTool(),
        WriteTool(),
        EditTool(),
        BashTool(
            default_timeout=config.bash_timeout_seconds,
            head_chars=config.bash_truncate_head,
            tail_chars=config.bash_truncate_tail,
        ),
    ]


def default_tools(config: Config) -> ToolRegistry:
    return ToolRegistry(_core_tools(config))


def headless_tools(config: Config) -> ToolRegistry:
    return ToolRegistry([*_core_tools(config), SubmitTool()])
