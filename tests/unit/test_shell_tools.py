"""M3.4 run_shell 工具的参数和状态映射测试。"""

from dataclasses import dataclass

from repopilot.execution import (
    CommandExecutionStatus,
    ShellExecutionRequest,
    ShellExecutionResult,
)
from repopilot.runtime.tool import ToolCall, ToolResultStatus
from repopilot.tools import ToolRegistry, register_shell_tool


@dataclass
class FakeCommandGateway:
    """记录命令请求并返回预设状态。"""

    result: ShellExecutionResult
    request: ShellExecutionRequest | None = None

    async def execute_command(
        self,
        request: ShellExecutionRequest,
    ) -> ShellExecutionResult:
        self.request = request
        return self.result


def make_result(status: CommandExecutionStatus) -> ShellExecutionResult:
    """创建一个简短的命令执行摘要。"""

    return ShellExecutionResult(
        status=status,
        exit_code=0 if status is CommandExecutionStatus.COMPLETED else None,
        stdout="ok",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=1,
    )


async def test_run_shell_passes_argument_array_to_gateway() -> None:
    """run_shell 不应把命令数组拼成宿主机 Shell 字符串。"""

    gateway = FakeCommandGateway(make_result(CommandExecutionStatus.COMPLETED))
    registry = ToolRegistry()
    register_shell_tool(registry, gateway)

    result = await registry.execute(
        ToolCall(
            name="run_shell",
            arguments={"command": ["pytest", "-q"], "cwd": "src"},
        )
    )

    assert result.status is ToolResultStatus.COMPLETED
    assert gateway.request is not None
    assert gateway.request.command == ("pytest", "-q")
    assert gateway.request.cwd == "src"


async def test_run_shell_maps_timeout_to_structured_tool_status() -> None:
    """命令超时应保留执行摘要，并映射为统一 TIMEOUT。"""

    gateway = FakeCommandGateway(make_result(CommandExecutionStatus.TIMEOUT))
    registry = ToolRegistry()
    register_shell_tool(registry, gateway)

    result = await registry.execute(
        ToolCall(name="run_shell", arguments={"command": ["pytest"]})
    )

    assert result.status is ToolResultStatus.TIMEOUT
    assert result.output is not None


async def test_run_shell_rejects_string_command() -> None:
    """字符串命令会绕过参数边界，因此必须被拒绝。"""

    gateway = FakeCommandGateway(make_result(CommandExecutionStatus.COMPLETED))
    registry = ToolRegistry()
    register_shell_tool(registry, gateway)

    result = await registry.execute(
        ToolCall(name="run_shell", arguments={"command": "pytest -q"})
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
