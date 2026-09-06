from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from uuid import UUID


class TaskEventType(str, Enum):
    TASK_CREATED = "task.created"
    TASK_QUEUED = "task.queued"


@dataclass(frozen=True)
class TaskEvent:
    task_id: UUID
    event_type: TaskEventType
    node: str
    payload: dict[str, str]
    sequence: int
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )