"""经过 Execution Gateway 执行的工作区写工具。

本模块负责把模型提供的参数验证并转换成明确的执行请求。是否允许调用、
是否需要审批由 ``ToolOrchestrator`` 决定；实际文件写入由
``ExecutionGateway`` 完成。
"""

from collections.abc import Mapping
from dataclasses import dataclass

from repopilot.execution import (
    ExecutionGateway,
    WriteFileExecutionRequest,
)
from repopilot.runtime.tool import ToolDefinition
from repopilot.tools.registry import ToolRegistry


@dataclass(frozen=True)
class WorkspaceWriteTools:
    """将模型参数转换为受控执行请求的副作用工具集合。"""

    gateway: ExecutionGateway

    async def write_file(self, arguments: Mapping[str, object]) -> object:
        """写入一个 UTF-8 文本文件，并返回结构化执行证据。"""

        path = self._required_string(arguments.get("path"), "path")
        content = self._required_content(arguments.get("content"))
        overwrite = self._optional_bool(
            arguments.get("overwrite", False),
            "overwrite",
        )
        create_parent_dirs = self._optional_bool(
            arguments.get("create_parent_dirs", False),
            "create_parent_dirs",
        )

        result = await self.gateway.write_file(
            WriteFileExecutionRequest(
                path=path,
                content=content,
                overwrite=overwrite,
                create_parent_dirs=create_parent_dirs,
            )
        )
        return {
            "path": result.path,
            "bytes_written": result.bytes_written,
            "created": result.created,
            "sha256": result.sha256,
            "previous_sha256": result.previous_sha256,
        }

    @staticmethod
    def _required_string(value: object, name: str) -> str:
        """读取必填非空字符串参数。"""

        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string.")
        return value

    @staticmethod
    def _required_content(value: object) -> str:
        """读取文件内容；空字符串合法，但其他类型必须拒绝。"""

        if not isinstance(value, str):
            raise ValueError("content must be a string.")
        return value

    @staticmethod
    def _optional_bool(value: object, name: str) -> bool:
        """读取可选布尔参数，避免把字符串 ``"false"`` 当成真值。"""

        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean.")
        return value


def register_write_tools(
    registry: ToolRegistry,
    gateway: ExecutionGateway,
) -> WorkspaceWriteTools:
    """把第一批副作用工具注册到现有 ToolRegistry。"""

    tools = WorkspaceWriteTools(gateway=gateway)
    registry.register(
        ToolDefinition(
            name="write_file",
            description=(
                "在任务工作区内写入 UTF-8 文本文件。已有文件只有在 "
                "overwrite=true 时才会被替换；父目录只有在 "
                "create_parent_dirs=true 时才会创建。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于任务工作区的文件路径。",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的完整 UTF-8 文本内容。",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "是否允许替换已有文件，默认 false。",
                    },
                    "create_parent_dirs": {
                        "type": "boolean",
                        "description": "是否创建缺失的父目录，默认 false。",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            read_only=False,
        ),
        tools.write_file,
    )
    return tools
