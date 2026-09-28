"""工具注册表和只读工具执行边界。

M2 只允许注册 read-only 工具。注册表负责名称解析、定义暴露和异常
标准化，不负责模型推理，也不负责未来的审批或 Docker 沙箱。
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

from repopilot.runtime.tool import (
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultStatus,
)

ToolHandler = Callable[[Mapping[str, object]], Awaitable[object]]


@dataclass(frozen=True)
class RegisteredTool:
    """工具定义与其异步处理函数的绑定。"""

    definition: ToolDefinition
    handler: ToolHandler


def _new_tool_map() -> dict[str, RegisteredTool]:
    """创建独立的工具注册表。"""

    return {}


@dataclass
class ToolRegistry:
    """解析并执行 M2 阶段允许的只读工具。"""

    _tools: dict[str, RegisteredTool] = field(default_factory=_new_tool_map)

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
    ) -> None:
        """注册一个工具，并拒绝 M2 暂不支持的副作用工具。"""

        if not definition.read_only:
            raise ValueError(
                "M2 ToolRegistry only accepts read-only tools."
            )

        if definition.name in self._tools:
            raise ValueError(f"Tool '{definition.name}' is already registered.")

        self._tools[definition.name] = RegisteredTool(
            definition=definition,
            handler=handler,
        )

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """按名称稳定返回工具定义，供模型请求使用。"""

        return tuple(
            registered.definition
            for registered in sorted(
                self._tools.values(),
                key=lambda item: item.definition.name,
            )
        )

    async def execute(self, call: ToolCall) -> ToolResult:
        """执行工具并把异常统一转换为 ToolResult。"""

        registered = self._tools.get(call.name)

        if registered is None:
            return ToolResult(
                tool_call_id=call.id,
                status=ToolResultStatus.REJECTED,
                error=f"Tool '{call.name}' is not registered.",
            )

        try:
            output = await registered.handler(call.arguments)
        except Exception as error:
            return ToolResult(
                tool_call_id=call.id,
                status=ToolResultStatus.FAILED,
                error=str(error),
            )

        return ToolResult(
            tool_call_id=call.id,
            status=ToolResultStatus.COMPLETED,
            output=output,
        )
