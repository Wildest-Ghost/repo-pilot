from dataclasses import dataclass, field
from uuid import UUID

from repopilot.domain.event import TaskEvent
from repopilot.domain.task import Task
from repopilot.services.task_repository import TaskRepository


@dataclass
class InMemoryTaskRepository(TaskRepository):
    _tasks: dict[UUID, Task] = field(default_factory=dict)
    _events: dict[UUID, list[TaskEvent]] = field(default_factory=dict)

    def save_task(self, task: Task) -> None:
        self._tasks[task.id] = task
        self._events.setdefault(task.id, [])

    def get_task(self, task_id: UUID) -> Task | None:
        return self._tasks.get(task_id)

    def append_event(self, event: TaskEvent) -> None:
        self._events[event.task_id].append(event)

    def get_events(self, task_id: UUID) -> list[TaskEvent]:
        return list(self._events.get(task_id, []))