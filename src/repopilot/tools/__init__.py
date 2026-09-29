"""结构化工具定义与 Tool Registry（工具注册表）边界。"""

from repopilot.tools.readonly import (
    ReadOnlyWorkspaceTools,
    build_read_only_registry,
)
from repopilot.tools.registry import (
    RegisteredTool,
    ToolExecutionFailure,
    ToolRegistry,
)
from repopilot.tools.shell import ShellWorkspaceTools, register_shell_tool
from repopilot.tools.write import WorkspaceWriteTools, register_write_tools

__all__ = [
    "ReadOnlyWorkspaceTools",
    "RegisteredTool",
    "ShellWorkspaceTools",
    "ToolExecutionFailure",
    "ToolRegistry",
    "WorkspaceWriteTools",
    "build_read_only_registry",
    "register_write_tools",
    "register_shell_tool",
]
