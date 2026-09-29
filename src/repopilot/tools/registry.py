"""工具注册表和底层处理器绑定。

注册表负责名称解析、定义暴露和异常标准化，不负责模型推理、策略审批
或 Docker 沙箱。M2 的默认工具仍然全部是只读工具；M3 开始允许注册副作用
工具，但它们必须通过 ``ToolOrchestrator`` 执行，不能被 HarnessLoop 直接绕过治理。
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

from repopilot.runtime.artifact import Artifact
from repopilot.runtime.tool import (
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultStatus,
)

ToolHandler = Callable[[Mapping[str, object]], Awaitable[object]]


class ToolExecutionFailure(Exception):
    """工具处理器用来返回结构化失败状态的受控异常。

    普通异常仍然会被注册表转换为 ``FAILED``。需要表达超时、取消或
    ``UNKNOWN_OUTCOME`` 的工具可以抛出本异常，从而保留状态、有限输出和
    产物引用，而不会把这些信息丢失在异常字符串中。
    """

    def __init__(
        self,
        *,
        status: ToolResultStatus,
        output: object | None = None,
        error: str | None = None,
        artifacts: tuple[Artifact, ...] = (),
    ) -> None:
        self.status = status
        self.output = output
        self.error = error
        self.artifacts = artifacts
        super().__init__(error or status.value)


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
    """保存工具定义，并调用已注册的底层异步处理器。"""

    _tools: dict[str, RegisteredTool] = field(default_factory=_new_tool_map)

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
    ) -> None:
        """注册工具；是否允许执行由 ToolOrchestrator 的策略决定。"""

        if definition.name in self._tools:
            raise ValueError(f"Tool '{definition.name}' is already registered.")

        self._tools[definition.name] = RegisteredTool(
            definition=definition,
            handler=handler,
        )

    def get_definition(self, name: str) -> ToolDefinition | None:
        """按名称读取工具定义，供策略引擎执行风险判断。"""

        registered = self._tools.get(name)
        return registered.definition if registered is not None else None

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
        except ToolExecutionFailure as error:
            return ToolResult(
                tool_call_id=call.id,
                status=error.status,
                output=error.output,
                error=error.error,
                artifacts=error.artifacts,
            )
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
