"""Agent Runtime 事件契约与事件存储端口。"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4


class RuntimeEventType(StrEnum):
    """当前运行时需要记录的事实类型。"""

    SESSION_CREATED = "session.created"
    TURN_CREATED = "turn.created"
    STEP_CREATED = "step.created"
    MODEL_REQUESTED = "model.requested"
    MODEL_RESPONDED = "model.responded"
    TOOL_CALL_REQUESTED = "tool_call.requested"
    TOOL_RESULT_RECORDED = "tool_result.recorded"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_RESOLVED = "approval.resolved"
    ARTIFACT_RECORDED = "artifact.recorded"
    STATUS_CHANGED = "status.changed"


def _new_payload() -> dict[str, object]:
    """创建事件负载的明确类型默认值。"""

    return {}


@dataclass(frozen=True)
class RuntimeEvent:
    """表示 AgentRun 内的一条有序、不可变运行事实。"""

    agent_run_id: UUID
    event_type: RuntimeEventType
    subject_id: UUID
    sequence: int
    id: UUID = field(default_factory=uuid4)
    payload: Mapping[str, object] = field(default_factory=_new_payload)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class EventSink(Protocol):
    """运行时事件追加和读取的最小端口。"""

    def append(self, event: RuntimeEvent) -> None:
        """追加一条事件。"""

        ...

    def get_events(self, agent_run_id: UUID) -> tuple[RuntimeEvent, ...]:
        """读取一个 AgentRun 的完整事件序列。"""

        ...
