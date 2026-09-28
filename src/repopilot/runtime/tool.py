"""结构化工具调用与工具结果契约。"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4

from repopilot.runtime.artifact import Artifact


def _new_parameters() -> dict[str, object]:
    """创建工具参数 Schema 的明确类型默认值。"""

    return {}


@dataclass(frozen=True)
class ToolDefinition:
    """描述模型可以请求的一个工具。"""

    name: str
    description: str
    parameters: Mapping[str, object] = field(default_factory=_new_parameters)
    read_only: bool = True

    def __post_init__(self) -> None:
        """校验工具名，避免注册无法被模型引用的工具。"""

        if not self.name.strip():
            raise ValueError("Tool name must not be empty.")


@dataclass(frozen=True)
class ToolCall:
    """表示模型提出的一次结构化工具调用。"""

    name: str
    id: UUID = field(default_factory=uuid4)
    arguments: Mapping[str, object] = field(default_factory=_new_parameters)
    provider_call_id: str | None = None


class ToolResultStatus(StrEnum):
    """工具执行结果的统一状态集合。"""

    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    APPROVAL_REQUIRED = "approval_required"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    UNKNOWN_OUTCOME = "unknown_outcome"


@dataclass(frozen=True)
class ToolResult:
    """表示一次 ToolCall 的结构化执行结果。"""

    tool_call_id: UUID
    status: ToolResultStatus
    output: object | None = None
    error: str | None = None
    artifacts: tuple[Artifact, ...] = ()
