"""Task 生命周期事件的领域表示。

事件是面向审计和恢复的事实记录，因此使用不可变 dataclass，
避免事件创建后被业务代码意外修改。
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID


class TaskEventType(StrEnum):
    """当前 Task 生命周期中可被记录的事件类型。"""

    TASK_CREATED = "task.created"
    TASK_QUEUED = "task.queued"


@dataclass(frozen=True)
class TaskEvent:
    """表示一次已经发生的 Task 领域事件。"""

    task_id: UUID
    event_type: TaskEventType
    node: str
    payload: dict[str, str]
    sequence: int
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
