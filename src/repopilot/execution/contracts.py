"""Execution Gateway（执行网关）的稳定契约。

执行网关只接收已经通过 Harness 策略和审批的执行请求。它不知道模型如何
产生 Tool Call，也不决定动作是否允许。文件写入和命令执行使用独立的
请求/结果类型，避免把短文件操作和长进程生命周期混成一个接口。
"""

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


@dataclass(frozen=True)
class WriteFileExecutionRequest:
    """一次受控文件写入请求。

    ``path`` 必须是相对于任务工作区的路径。``overwrite`` 和
    ``create_parent_dirs`` 默认关闭，要求调用方明确表达更强的副作用意图。
    """

    path: str
    content: str
    overwrite: bool = False
    create_parent_dirs: bool = False


@dataclass(frozen=True)
class WriteFileExecutionResult:
    """文件写入完成后的结构化证据。"""

    path: str
    bytes_written: int
    created: bool
    sha256: str
    previous_sha256: str | None = None


class CommandExecutionStatus(StrEnum):
    """命令执行结果的基础状态。

    ``UNKNOWN_OUTCOME`` 专门表示进程已经启动，但网关在确认最终状态前
    丢失了控制权。Harness 不应把这种结果当作可以安全重试的普通失败。
    """

    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    UNKNOWN_OUTCOME = "unknown_outcome"


@dataclass(frozen=True)
class ShellExecutionRequest:
    """一次受控、非 Shell 字符串拼接的命令执行请求。"""

    command: tuple[str, ...]
    cwd: str = "."
    timeout_seconds: float = 30.0
    max_output_bytes: int = 64 * 1024
    cancel_event: asyncio.Event | None = None

    def __post_init__(self) -> None:
        """在进入 Docker 前校验命令和资源限制。"""

        if not self.command or any(not part.strip() for part in self.command):
            raise ValueError("command must contain at least one non-empty string.")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        if self.max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive.")


@dataclass(frozen=True)
class ShellExecutionResult:
    """Docker 命令执行后的有限、可审计摘要。"""

    status: CommandExecutionStatus
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: int


class ExecutionGateway(Protocol):
    """执行已批准动作的异步端口。"""

    async def write_file(
        self,
        request: WriteFileExecutionRequest,
    ) -> WriteFileExecutionResult:
        """在受控工作区中原子写入一个 UTF-8 文本文件。"""

        ...


class CommandExecutionGateway(Protocol):
    """执行受控命令的异步端口。"""

    async def execute_command(
        self,
        request: ShellExecutionRequest,
    ) -> ShellExecutionResult:
        """在隔离执行环境中运行一个参数数组命令。"""

        ...
