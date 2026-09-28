"""模型后端的 provider-neutral（提供方无关）契约。

Harness 只依赖本模块定义的请求和响应类型，不直接依赖 DeepSeek SDK。
后续的 DeepSeekBackend、FakeBackend 或其他模型适配器都实现同一个端口。
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from repopilot.runtime.messages import Message
from repopilot.runtime.tool import ToolCall, ToolDefinition


def _new_usage() -> dict[str, int]:
    """创建 Token 使用量的明确类型默认值。"""

    return {}


@dataclass(frozen=True)
class ModelRequest:
    """一次模型请求及其受控上下文。"""

    model: str
    session_id: UUID
    turn_id: UUID
    step_id: UUID
    messages: tuple[Message, ...] = ()
    tools: tuple[ToolDefinition, ...] = ()


@dataclass(frozen=True)
class ModelResponse:
    """一次模型响应的统一表示。"""

    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str = "stop"
    usage: Mapping[str, int] = field(default_factory=_new_usage)


class AgentBackend(Protocol):
    """模型后端必须实现的最小调用端口。"""

    @property
    def backend_name(self) -> str:
        """返回稳定的后端标识，例如 deepseek 或 fake。"""

        ...

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """根据请求生成一次模型响应。"""

        ...
