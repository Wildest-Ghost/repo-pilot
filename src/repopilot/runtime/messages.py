"""RepoPilot 内部统一消息格式。

Harness 只处理这些内部消息类型，不直接操作 DeepSeek 或其他模型提供方
的原始消息字典。具体协议转换由 AgentBackend 适配器负责。
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from repopilot.runtime.tool import ToolCall, ToolResultStatus


class MessageRole(StrEnum):
    """内部消息的角色集合。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class SystemMessage:
    """由 Harness 注入的系统约束或运行说明。"""

    content: str
    role: ClassVar[MessageRole] = MessageRole.SYSTEM


@dataclass(frozen=True)
class UserMessage:
    """用户提交的任务或恢复指令。"""

    content: str
    role: ClassVar[MessageRole] = MessageRole.USER


@dataclass(frozen=True)
class AssistantMessage:
    """模型生成的文本和工具调用意图。"""

    content: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    role: ClassVar[MessageRole] = MessageRole.ASSISTANT


@dataclass(frozen=True)
class ToolMessage:
    """Harness 执行工具后返回给模型的结构化结果。"""

    tool_call_id: UUID
    content: object
    status: ToolResultStatus
    role: ClassVar[MessageRole] = MessageRole.TOOL


type Message = SystemMessage | UserMessage | AssistantMessage | ToolMessage
