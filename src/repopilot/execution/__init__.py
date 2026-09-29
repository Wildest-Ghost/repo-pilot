"""受控副作用执行边界。"""

from repopilot.execution.contracts import (
    CommandExecutionGateway,
    CommandExecutionStatus,
    ExecutionGateway,
    ShellExecutionRequest,
    ShellExecutionResult,
    WriteFileExecutionRequest,
    WriteFileExecutionResult,
)
from repopilot.execution.docker import DockerExecutionGateway
from repopilot.execution.local import LocalExecutionGateway

__all__ = [
    "CommandExecutionGateway",
    "CommandExecutionStatus",
    "DockerExecutionGateway",
    "ExecutionGateway",
    "LocalExecutionGateway",
    "ShellExecutionRequest",
    "ShellExecutionResult",
    "WriteFileExecutionRequest",
    "WriteFileExecutionResult",
]
