"""基于 Docker 的受控命令执行网关。

该模块是 M3.4 的第一版沙箱边界。模型只能提供参数数组，网关负责构造
固定的 ``docker run`` 参数，默认关闭网络、丢弃 Linux capabilities、限制
资源，并把工作区以单个 bind mount 暴露给容器。它不会把用户输入拼成
宿主机 Shell 字符串。

本模块只报告执行事实，不决定工具是否需要审批；审批仍由
``ToolOrchestrator`` 在调用网关前完成。
"""

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from repopilot.execution.contracts import (
    CommandExecutionGateway,
    CommandExecutionStatus,
    ShellExecutionRequest,
    ShellExecutionResult,
)

_CHUNK_SIZE: Final[int] = 8192
_PROCESS_CLEANUP_TIMEOUT: Final[float] = 2.0


@dataclass(frozen=True)
class DockerExecutionGateway(CommandExecutionGateway):
    """把命令执行限制在任务工作区和 Docker 容器内。"""

    root: Path
    image: str = "python:3.12-slim"
    docker_binary: str = "docker"
    default_timeout_seconds: float = 30.0
    max_output_bytes: int = 64 * 1024
    memory_limit: str = "512m"
    cpus: float = 1.0
    network_enabled: bool = False
    user: str = "65532:65532"

    def __post_init__(self) -> None:
        """固定工作区并校验沙箱资源配置。"""

        resolved_root = self.root.resolve()
        if not resolved_root.is_dir():
            raise ValueError("Execution workspace root must be a directory.")
        if not self.image.strip():
            raise ValueError("Docker image must not be empty.")
        if not self.docker_binary.strip():
            raise ValueError("docker_binary must not be empty.")
        if self.default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be positive.")
        if self.max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive.")
        if self.cpus <= 0:
            raise ValueError("cpus must be positive.")
        object.__setattr__(self, "root", resolved_root)

    async def execute_command(
        self,
        request: ShellExecutionRequest,
    ) -> ShellExecutionResult:
        """在 Docker 中执行命令，并有界读取标准输出和标准错误。"""

        if request.cancel_event is not None and request.cancel_event.is_set():
            return self._result(
                status=CommandExecutionStatus.CANCELLED,
                exit_code=None,
                stdout=b"",
                stderr=b"cancelled before process start",
                stdout_truncated=False,
                stderr_truncated=False,
                started_at=time.monotonic(),
            )

        cwd = self._resolve_cwd(request.cwd)
        command = self._docker_command(cwd, request.command)
        started_at = time.monotonic()

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            return self._result(
                status=CommandExecutionStatus.FAILED,
                exit_code=None,
                stdout=b"",
                stderr=str(error).encode("utf-8", errors="replace"),
                stdout_truncated=False,
                stderr_truncated=False,
                started_at=started_at,
            )

        if process.stdout is None or process.stderr is None:
            await self._terminate(process)
            return self._result(
                status=CommandExecutionStatus.UNKNOWN_OUTCOME,
                exit_code=None,
                stdout=b"",
                stderr=b"Docker process did not expose output streams.",
                stdout_truncated=False,
                stderr_truncated=False,
                started_at=started_at,
            )

        output_limit = min(request.max_output_bytes, self.max_output_bytes)
        stdout_task = asyncio.create_task(
            self._read_bounded(process.stdout, output_limit)
        )
        stderr_task = asyncio.create_task(
            self._read_bounded(process.stderr, output_limit)
        )
        wait_task = asyncio.create_task(process.wait())
        cancel_task = (
            asyncio.create_task(request.cancel_event.wait())
            if request.cancel_event is not None
            else None
        )

        try:
            wait_set = {wait_task}
            if cancel_task is not None:
                wait_set.add(cancel_task)
            done, _ = await asyncio.wait(
                wait_set,
                timeout=request.timeout_seconds or self.default_timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if not done:
                await self._terminate(process)
                status = CommandExecutionStatus.TIMEOUT
                exit_code = None
            elif cancel_task is not None and cancel_task in done:
                await self._terminate(process)
                status = CommandExecutionStatus.CANCELLED
                exit_code = None
            else:
                exit_code = wait_task.result()
                status = (
                    CommandExecutionStatus.COMPLETED
                    if exit_code == 0
                    else CommandExecutionStatus.FAILED
                )

            stdout, stdout_truncated = await stdout_task
            stderr, stderr_truncated = await stderr_task
            return self._result(
                status=status,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
                started_at=started_at,
            )
        except asyncio.CancelledError:
            await self._terminate(process)
            raise
        except Exception as error:
            await self._terminate(process)
            return self._result(
                status=CommandExecutionStatus.UNKNOWN_OUTCOME,
                exit_code=None,
                stdout=b"",
                stderr=str(error).encode("utf-8", errors="replace"),
                stdout_truncated=False,
                stderr_truncated=False,
                started_at=started_at,
            )
        finally:
            for task in (wait_task, cancel_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                wait_task,
                *(task for task in (cancel_task,) if task is not None),
                return_exceptions=True,
            )

    def _docker_command(
        self,
        cwd: Path,
        command: tuple[str, ...],
    ) -> tuple[str, ...]:
        """构造不经过宿主 Shell 解析的 Docker 参数数组。"""

        network = "bridge" if self.network_enabled else "none"
        relative_cwd = cwd.relative_to(self.root).as_posix()
        container_cwd = (
            "/workspace"
            if relative_cwd == "."
            else f"/workspace/{relative_cwd}"
        )
        return (
            self.docker_binary,
            "run",
            "--rm",
            "--init",
            "--network",
            network,
            "--cpus",
            str(self.cpus),
            "--memory",
            self.memory_limit,
            "--pids-limit",
            "128",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--user",
            self.user,
            "--mount",
            f"type=bind,source={self.root},target=/workspace",
            "--workdir",
            container_cwd,
            self.image,
            *command,
        )

    def _resolve_cwd(self, value: str) -> Path:
        """把工作目录限制在任务工作区内。"""

        if not value.strip():
            raise ValueError("cwd must be a non-empty relative path.")
        path = Path(value)
        if path.is_absolute():
            raise ValueError("cwd must be relative to the workspace.")
        resolved = (self.root / path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as error:
            raise ValueError("cwd must stay inside the workspace.") from error
        if not resolved.is_dir():
            raise ValueError("cwd must point to a directory inside the workspace.")
        return resolved

    @staticmethod
    async def _read_bounded(
        stream: asyncio.StreamReader,
        limit: int,
    ) -> tuple[bytes, bool]:
        """持续消费输出避免子进程阻塞，同时只保留有界前缀。"""

        chunks: list[bytes] = []
        size = 0
        truncated = False
        while chunk := await stream.read(_CHUNK_SIZE):
            if size < limit:
                kept = chunk[: limit - size]
                chunks.append(kept)
                size += len(kept)
                truncated = truncated or len(kept) < len(chunk)
            else:
                truncated = True
        return b"".join(chunks), truncated

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        """尽力终止 Docker CLI，避免超时后留下失控进程。"""

        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), _PROCESS_CLEANUP_TIMEOUT)
        except TimeoutError:
            process.kill()
            await process.wait()

    def _result(
        self,
        *,
        status: CommandExecutionStatus,
        exit_code: int | None,
        stdout: bytes,
        stderr: bytes,
        stdout_truncated: bool,
        stderr_truncated: bool,
        started_at: float,
    ) -> ShellExecutionResult:
        """统一生成解码后的有限执行摘要。"""

        return ShellExecutionResult(
            status=status,
            exit_code=exit_code,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            duration_ms=max(0, int((time.monotonic() - started_at) * 1000)),
        )
