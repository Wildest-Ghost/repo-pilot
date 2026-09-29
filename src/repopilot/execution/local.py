"""受限的本地 Execution Gateway。

该实现只用于本地开发和 M3.3 契约验证。它把所有路径限制在显式工作区中，
限制单次写入大小，并通过“同目录临时文件 + os.replace”完成原子替换。
它不会执行 Shell、访问网络或删除任意文件。
"""

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from repopilot.execution.contracts import (
    ExecutionGateway,
    WriteFileExecutionRequest,
    WriteFileExecutionResult,
)

_DEFAULT_MAX_WRITE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class LocalExecutionGateway(ExecutionGateway):
    """把受控文件操作限定在一个本地任务工作区内。"""

    root: Path
    max_write_bytes: int = _DEFAULT_MAX_WRITE_BYTES

    def __post_init__(self) -> None:
        """固定工作区绝对路径，并校验写入上限。"""

        resolved_root = self.root.resolve()
        if not resolved_root.is_dir():
            raise ValueError("Execution workspace root must be a directory.")
        if self.max_write_bytes <= 0:
            raise ValueError("max_write_bytes must be positive.")

        object.__setattr__(self, "root", resolved_root)

    async def write_file(
        self,
        request: WriteFileExecutionRequest,
    ) -> WriteFileExecutionResult:
        """执行一次有大小限制的原子文件写入。

        本地版本有意同步完成最多 1 MiB 的短文件操作，使协程只有在原子替换
        已明确完成后才返回。这样取消不会把仍在后台运行的线程遗留为未知结果。
        Docker 网关中的长任务会使用独立进程生命周期和异步取消机制。
        """

        target = self._resolve_relative_path(request.path)
        content_bytes = request.content.encode("utf-8")

        if len(content_bytes) > self.max_write_bytes:
            raise ValueError(
                "File content exceeds the configured write size limit."
            )

        existed = target.exists()
        if existed and not target.is_file():
            raise ValueError("Target path is not a regular file.")
        if existed and not request.overwrite:
            raise FileExistsError(
                "Target file already exists; set overwrite=true to replace it."
            )

        parent = target.parent
        if not parent.exists():
            if not request.create_parent_dirs:
                raise FileNotFoundError(
                    "Parent directory does not exist; "
                    "set create_parent_dirs=true to create it."
                )
            parent.mkdir(parents=True, exist_ok=True)

        if not parent.is_dir():
            raise ValueError("Target parent is not a directory.")

        previous_sha256 = (
            self._sha256(target.read_bytes())
            if existed
            else None
        )
        temporary_path = self._write_temporary_file(parent, content_bytes)

        try:
            os.replace(temporary_path, target)
        finally:
            # os.replace 成功后临时路径已经不存在；失败时清理残留，避免工作区
            # 被半成品污染。
            temporary_path.unlink(missing_ok=True)

        return WriteFileExecutionResult(
            path=target.relative_to(self.root).as_posix(),
            bytes_written=len(content_bytes),
            created=not existed,
            sha256=self._sha256(content_bytes),
            previous_sha256=previous_sha256,
        )

    def _resolve_relative_path(self, value: str) -> Path:
        """解析相对路径，并拒绝绝对路径和工作区逃逸。"""

        if not value.strip():
            raise ValueError("path must be a non-empty string.")

        relative_path = Path(value)
        if relative_path.is_absolute():
            raise ValueError("path must be relative to the workspace.")

        target = (self.root / relative_path).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as error:
            raise ValueError("path must stay inside the workspace.") from error

        if target == self.root:
            raise ValueError("path must point to a file inside the workspace.")
        return target

    @staticmethod
    def _write_temporary_file(parent: Path, content: bytes) -> Path:
        """在目标目录创建、刷盘并关闭临时文件。"""

        descriptor, raw_path = tempfile.mkstemp(
            prefix=".repopilot-write-",
            suffix=".tmp",
            dir=parent,
        )
        temporary_path = Path(raw_path)

        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

        return temporary_path

    @staticmethod
    def _sha256(content: bytes) -> str:
        """计算稳定的内容摘要，供审计和后续并发校验使用。"""

        return hashlib.sha256(content).hexdigest()
