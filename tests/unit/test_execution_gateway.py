"""M3.3 LocalExecutionGateway 的文件安全边界测试。"""

from pathlib import Path

import pytest

from repopilot.execution import (
    LocalExecutionGateway,
    WriteFileExecutionRequest,
)


async def test_local_gateway_writes_new_file_atomically(tmp_path: Path) -> None:
    """新文件应写入工作区，并返回字节数和摘要证据。"""

    gateway = LocalExecutionGateway(tmp_path)

    result = await gateway.write_file(
        WriteFileExecutionRequest(
            path="src/app.py",
            content="answer = 42\n",
            create_parent_dirs=True,
        )
    )

    target = tmp_path / "src" / "app.py"
    assert result.path == "src/app.py"
    assert result.bytes_written == len(b"answer = 42\n")
    assert result.created is True
    assert result.previous_sha256 is None
    assert target.read_text(encoding="utf-8") == "answer = 42\n"
    assert not list((tmp_path / "src").glob(".repopilot-write-*.tmp"))


async def test_local_gateway_rejects_workspace_escape(tmp_path: Path) -> None:
    """相对路径逃逸不能写入工作区之外。"""

    gateway = LocalExecutionGateway(tmp_path)

    with pytest.raises(ValueError, match="inside the workspace"):
        await gateway.write_file(
            WriteFileExecutionRequest(
                path="../outside.txt",
                content="should not be written",
            )
        )


async def test_local_gateway_rejects_absolute_path(tmp_path: Path) -> None:
    """绝对路径不能绕过任务工作区边界。"""

    gateway = LocalExecutionGateway(tmp_path)

    with pytest.raises(ValueError, match="must be relative"):
        await gateway.write_file(
            WriteFileExecutionRequest(
                path=str(tmp_path / "outside.txt"),
                content="should not be written",
            )
        )


async def test_local_gateway_requires_explicit_overwrite(tmp_path: Path) -> None:
    """已有文件必须显式设置 overwrite=true 才能替换。"""

    target = tmp_path / "README.md"
    target.write_text("old", encoding="utf-8")
    gateway = LocalExecutionGateway(tmp_path)

    with pytest.raises(FileExistsError, match="overwrite=true"):
        await gateway.write_file(
            WriteFileExecutionRequest(path="README.md", content="new")
        )

    assert target.read_text(encoding="utf-8") == "old"


async def test_local_gateway_overwrites_and_returns_previous_hash(
    tmp_path: Path,
) -> None:
    """显式覆盖应原子替换文件，并返回替换前后的摘要。"""

    target = tmp_path / "README.md"
    target.write_text("old", encoding="utf-8")
    gateway = LocalExecutionGateway(tmp_path)

    result = await gateway.write_file(
        WriteFileExecutionRequest(
            path="README.md",
            content="new",
            overwrite=True,
        )
    )

    assert result.created is False
    assert result.previous_sha256 is not None
    assert result.previous_sha256 != result.sha256
    assert target.read_text(encoding="utf-8") == "new"


async def test_local_gateway_enforces_utf8_byte_limit(tmp_path: Path) -> None:
    """大小限制按 UTF-8 字节数计算，而不是 Python 字符数。"""

    gateway = LocalExecutionGateway(tmp_path, max_write_bytes=4)

    with pytest.raises(ValueError, match="size limit"):
        await gateway.write_file(
            WriteFileExecutionRequest(path="message.txt", content="你好")
        )


async def test_local_gateway_requires_explicit_parent_creation(
    tmp_path: Path,
) -> None:
    """缺少父目录时必须显式允许创建目录。"""

    gateway = LocalExecutionGateway(tmp_path)

    with pytest.raises(FileNotFoundError, match="create_parent_dirs"):
        await gateway.write_file(
            WriteFileExecutionRequest(path="new/app.py", content="pass")
        )

    result = await gateway.write_file(
        WriteFileExecutionRequest(
            path="new/app.py",
            content="pass",
            create_parent_dirs=True,
        )
    )
    assert result.path == "new/app.py"
