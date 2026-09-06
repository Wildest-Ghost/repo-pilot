from typing import Protocol
from uuid import UUID

from repopilot.domain.event import TaskEvent
from repopilot.domain.task import Task


class TaskRepository(Protocol):
    def save_task(self, task: Task) -> None:
        ...

    def get_task(self, task_id: UUID) -> Task | None:
        ...

    def append_event(self, event: TaskEvent) -> None:
        ...

    def get_events(self, task_id: UUID) -> list[TaskEvent]:
        ...