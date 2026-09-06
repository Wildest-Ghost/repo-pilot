from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import ClassVar
from uuid import UUID, uuid4


class TaskStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvalidTaskTransitionError(ValueError):
    """Raised when a task attempts an invalid status transition."""


@dataclass
class Task:
    instruction: str
    id: UUID = field(default_factory=uuid4)
    status: TaskStatus = TaskStatus.CREATED
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    _ALLOWED_TRANSITIONS: ClassVar[dict[TaskStatus, frozenset[TaskStatus]]] = {
        TaskStatus.CREATED: frozenset({TaskStatus.QUEUED}),
        TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
        TaskStatus.RUNNING: frozenset(
            {
                TaskStatus.SUCCEEDED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }
        ),
        TaskStatus.SUCCEEDED: frozenset(),
        TaskStatus.FAILED: frozenset(),
        TaskStatus.CANCELLED: frozenset(),
    }

    def __post_init__(self) -> None:
        self.instruction = self.instruction.strip()

        if not self.instruction:
            raise ValueError("Task instruction must not be empty.")

    def transition_to(self, target_status: TaskStatus) -> None:
        allowed_statuses = self._ALLOWED_TRANSITIONS[self.status]

        if target_status not in allowed_statuses:
            raise InvalidTaskTransitionError(
                f"Cannot transition task from '{self.status.value}' "
                f"to '{target_status.value}'."
            )

        self.status = target_status
        self.updated_at = datetime.now(UTC)