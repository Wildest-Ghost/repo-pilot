"""M3.4 DockerExecutionGateway 的沙箱参数、输出和超时测试。"""

import asyncio
from pathlib import Path
from typing import cast

import pytest

from repopilot.execution import (
    CommandExecutionStatus,
    DockerExecutionGateway,
    ShellExecutionRequest,
)


class FakeProcess:
    """模拟 Docker CLI 进程，避免单元测试依赖本地镜像。"""

    def __init__(self, *, stdout: bytes, stderr: bytes, exit_code: int | None):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.returncode = exit_code
        self._finished = asyncio.Event()
        if exit_code is not None:
            self._finished.set()
        self.stdout.feed_data(stdout)
        self.stdout.feed_eof()
        self.stderr.feed_data(stderr)
        self.stderr.feed_eof()

    async def wait(self) -> int:
        """等待模拟进程结束。"""

        await self._finished.wait()
        return self.returncode or 0

    def terminate(self) -> None:
        """模拟终止并关闭输出流。"""

        self.returncode = -15
        self._finished.set()
        self.stdout.feed_eof()
        self.stderr.feed_eof()

    def kill(self) -> None:
        """模拟强制终止。"""

        self.terminate()


async def test_docker_gateway_uses_restricted_exec_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功执行时应使用禁网、降权和资源限制参数。"""

    captured: list[object] = []
    process = FakeProcess(stdout=b"ok\n", stderr=b"", exit_code=0)

    async def fake_create_subprocess_exec(*args: object, **kwargs: object):
        captured.extend(args)
        return cast(asyncio.subprocess.Process, process)

    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await DockerExecutionGateway(tmp_path).execute_command(
        ShellExecutionRequest(command=("pytest", "-q"))
    )

    assert result.status is CommandExecutionStatus.COMPLETED
    assert result.exit_code == 0
    assert result.stdout == "ok\n"
    assert "none" in captured
    assert "--cap-drop" in captured
    assert "ALL" in captured
    assert "--memory" in captured


async def test_docker_gateway_truncates_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超长 stdout 只能保留配置上限，并继续消费剩余内容。"""

    process = FakeProcess(stdout=b"123456789", stderr=b"", exit_code=0)

    async def fake_create_subprocess_exec(*args: object, **kwargs: object):
        return cast(asyncio.subprocess.Process, process)

    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await DockerExecutionGateway(tmp_path).execute_command(
        ShellExecutionRequest(command=("echo", "output"), max_output_bytes=4)
    )

    assert result.stdout == "1234"
    assert result.stdout_truncated is True


async def test_docker_gateway_terminates_timed_out_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超时应终止 Docker CLI，并返回可供 Harness 识别的状态。"""

    process = FakeProcess(stdout=b"", stderr=b"", exit_code=None)

    async def fake_create_subprocess_exec(*args: object, **kwargs: object):
        return cast(asyncio.subprocess.Process, process)

    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await DockerExecutionGateway(tmp_path).execute_command(
        ShellExecutionRequest(command=("sleep", "10"), timeout_seconds=0.01)
    )

    assert result.status is CommandExecutionStatus.TIMEOUT
    assert process.returncode == -15


async def test_docker_gateway_rejects_workspace_escape(tmp_path: Path) -> None:
    """容器工作目录不能逃逸任务工作区。"""

    gateway = DockerExecutionGateway(tmp_path)

    try:
        await gateway.execute_command(
            ShellExecutionRequest(command=("pytest",), cwd="../outside")
        )
    except ValueError as error:
        assert "inside the workspace" in str(error)
    else:
        raise AssertionError("workspace escape should be rejected")
