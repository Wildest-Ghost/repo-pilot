"""Agent Runtime（智能体运行时）的契约边界。

未来这里将承载 Session、Turn、事件契约和 Agent Backend 端口。
当前只先明确职责边界，不把 DeepSeek 适配器或执行循环的占位包误认为已实现。
"""

from repopilot.runtime.backend import (
    AgentBackend,
    ModelRequest,
    ModelResponse,
)
from repopilot.runtime.event_store import InMemoryEventStore
from repopilot.runtime.events import (
    EventSink,
    RuntimeEvent,
    RuntimeEventType,
)
from repopilot.runtime.fake_backend import FakeBackend
from repopilot.runtime.messages import (
    AssistantMessage,
    Message,
    MessageRole,
    SystemMessage,
    ToolMessage,
    UserMessage,
)
from repopilot.runtime.run import (
    AgentRun,
    AgentRunStatus,
    InvalidAgentRunTransitionError,
)
from repopilot.runtime.session import (
    InvalidStepTransitionError,
    InvalidTurnTransitionError,
    Session,
    Step,
    StepStatus,
    Turn,
    TurnKind,
    TurnStatus,
)
from repopilot.runtime.tool import (
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultStatus,
)

__all__ = [
    "AgentBackend",
    "AgentRun",
    "AgentRunStatus",
    "EventSink",
    "FakeBackend",
    "InMemoryEventStore",
    "InvalidStepTransitionError",
    "InvalidAgentRunTransitionError",
    "InvalidTurnTransitionError",
    "AssistantMessage",
    "Message",
    "MessageRole",
    "ModelRequest",
    "ModelResponse",
    "RuntimeEvent",
    "RuntimeEventType",
    "Session",
    "Step",
    "StepStatus",
    "SystemMessage",
    "ToolCall",
    "ToolDefinition",
    "ToolMessage",
    "ToolResult",
    "ToolResultStatus",
    "Turn",
    "TurnKind",
    "TurnStatus",
    "UserMessage",
]
