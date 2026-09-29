"""经过 Docker Execution Gateway 执行的受控 Shell 工具。

工具只接受参数数组，不接受一整段需要宿主 Shell 解析的字符串。实际命令
执行、网络策略、资源限制和进程清理由 ``DockerExecutionGateway`` 负责；
本模块只负责参数验证，以及把命令状态映射为统一 ``ToolResultStatus``。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from repopilot.execution import (
    CommandExecutionGateway,
    CommandExecutionStatus,
    ShellExecutionRequest,
)
from repopilot.runtime.tool import ToolDefinition, ToolResultStatus
from repopilot.tools.registry import (
    ToolExecutionFailure,
    ToolRegistry,
)


@dataclass(frozen=True)
class ShellWorkspaceTools:
    """将模型命令请求转换成 Docker 沙箱执行请求。"""

    gateway: CommandExecutionGateway

    async def run_shell(self, arguments: Mapping[str, object]) -> object:
        """运行一条受资源和输出限制的参数数组命令。"""

        command = self._command(arguments.get("command"))
        cwd = self._optional_string(arguments.get("cwd", "."), "cwd")
        timeout_seconds = self._positive_number(
            arguments.get("timeout_seconds", 30.0),
            "timeout_seconds",
        )
        max_output_bytes = self._positive_int(
            arguments.get("max_output_bytes", 64 * 1024),
            "max_output_bytes",
        )
        result = await self.gateway.execute_command(
            ShellExecutionRequest(
                command=command,
                cwd=cwd,
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
            )
        )
        output = {
            "status": result.status.value,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "stdout_truncated": result.stdout_truncated,
            "stderr_truncated": result.stderr_truncated,
            "duration_ms": result.duration_ms,
        }
        if result.status is CommandExecutionStatus.COMPLETED:
            return output

        raise ToolExecutionFailure(
            status=self._tool_status(result.status),
            output=output,
            error=result.stderr or f"Command ended with {result.status.value}.",
        )

    @staticmethod
    def _command(value: object) -> tuple[str, ...]:
        """只接受非空字符串数组，拒绝隐式 Shell 拼接。"""

        if not isinstance(value, (list, tuple)) or not value:
            raise ValueError("command must be a non-empty string array.")
        items = cast(list[object] | tuple[object, ...], value)
        if any(not isinstance(item, str) or not item.strip() for item in items):
            raise ValueError("command must contain only non-empty strings.")
        return tuple(cast(str, item) for item in items)

    @staticmethod
    def _optional_string(value: object, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string.")
        return value

    @staticmethod
    def _positive_number(value: object, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a positive number.")
        if value <= 0:
            raise ValueError(f"{name} must be a positive number.")
        return float(value)

    @staticmethod
    def _positive_int(value: object, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer.")
        return value

    @staticmethod
    def _tool_status(status: CommandExecutionStatus) -> ToolResultStatus:
        return {
            CommandExecutionStatus.FAILED: ToolResultStatus.FAILED,
            CommandExecutionStatus.TIMEOUT: ToolResultStatus.TIMEOUT,
            CommandExecutionStatus.CANCELLED: ToolResultStatus.CANCELLED,
            CommandExecutionStatus.UNKNOWN_OUTCOME: ToolResultStatus.UNKNOWN_OUTCOME,
            CommandExecutionStatus.COMPLETED: ToolResultStatus.COMPLETED,
        }[status]


def register_shell_tool(
    registry: ToolRegistry,
    gateway: CommandExecutionGateway,
) -> ShellWorkspaceTools:
    """注册需要审批的 ``run_shell`` 工具。"""

    tools = ShellWorkspaceTools(gateway=gateway)
    registry.register(
        ToolDefinition(
            name="run_shell",
            description=(
                "在 Docker 任务工作区中运行参数数组命令；默认关闭网络，"
                "并限制执行时间、资源和输出大小。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "命令及其参数，例如 ['pytest', '-q']。",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "工作区内的相对工作目录，默认 '.'。",
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "description": "单次执行的最大秒数。",
                    },
                    "max_output_bytes": {
                        "type": "integer",
                        "description": "标准输出和错误各自的保留上限。",
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            read_only=False,
        ),
        tools.run_shell,
    )
    return tools
