from dataclasses import dataclass, field
from uuid import UUID

from repopilot.domain.event import TaskEvent, TaskEventType
from repopilot.domain.task import Task, TaskStatus
from repopilot.infra.repositories.in_memory import InMemoryTaskRepository
from repopilot.services.task_repository import TaskRepository


class TaskNotFoundError(LookupError):
    """Raised when a requested task does not exist."""


@dataclass
class TaskService:
    repository: TaskRepository = field(
        default_factory=InMemoryTaskRepository
    )

    def create_task(self, instruction: str) -> Task:
        task = Task(instruction=instruction)
        self.repository.save_task(task)

        self._append_event(
            task_id=task.id,
            event_type=TaskEventType.TASK_CREATED,
            node="api.create_task",
            payload={"status": task.status.value},
        )

        return task

    def get_task(self, task_id: UUID) -> Task:
        task = self.repository.get_task(task_id)

        if task is None:
            raise TaskNotFoundError(f"Task '{task_id}' was not found.")

        return task

    def queue_task(self, task_id: UUID) -> Task:
        task = self.get_task(task_id)
        task.transition_to(TaskStatus.QUEUED)
        self.repository.save_task(task)

        self._append_event(
            task_id=task.id,
            event_type=TaskEventType.TASK_QUEUED,
            node="api.queue_task",
            payload={"status": task.status.value},
        )

        return task

    def get_events(self, task_id: UUID) -> list[TaskEvent]:
        self.get_task(task_id)
        return self.repository.get_events(task_id)

    def _append_event(
        self,
        task_id: UUID,
        event_type: TaskEventType,
        node: str,
        payload: dict[str, str],
    ) -> None:
        events = self.repository.get_events(task_id)

        event = TaskEvent(
            task_id=task_id,
            event_type=event_type,
            node=node,
            payload=payload,
            sequence=len(events) + 1,
        )

        self.repository.append_event(event)