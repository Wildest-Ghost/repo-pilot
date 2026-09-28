"""Task 应用服务。

本层编排领域对象与仓储端口，负责把一次业务操作落成 Task 状态和
有序事件。它不负责模型调用、工具执行或审批决策。
"""

from dataclasses import dataclass, field
from uuid import UUID

from repopilot.domain.event import TaskEvent, TaskEventType
from repopilot.domain.task import Task, TaskStatus
from repopilot.infra.repositories.in_memory import InMemoryTaskRepository
from repopilot.services.task_repository import TaskRepository


class TaskNotFoundError(LookupError):
    """请求的 Task 不存在时抛出。"""


@dataclass
class TaskService:
    """提供 Task 生命周期操作，并同步记录领域事件。"""

    repository: TaskRepository = field(
        default_factory=InMemoryTaskRepository
    )

    def create_task(self, instruction: str) -> Task:
        """创建 Task，并追加 `task.created` 事件。"""

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
        """读取 Task；不存在时抛出 `TaskNotFoundError`。"""

        task = self.repository.get_task(task_id)

        if task is None:
            raise TaskNotFoundError(f"Task '{task_id}' was not found.")

        return task

    def queue_task(self, task_id: UUID) -> Task:
        """将 Task 从 CREATED 迁移到 QUEUED，并记录事件。"""

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
        """读取 Task 的完整事件序列。"""

        self.get_task(task_id)
        return self.repository.get_events(task_id)

    def _append_event(
        self,
        task_id: UUID,
        event_type: TaskEventType,
        node: str,
        payload: dict[str, str],
    ) -> None:
        """为 Task 追加下一个有序事件。

        当前内存实现通过已有事件数量生成序号；接入并发持久化存储后，
        序号分配必须由事务或事件存储端原子完成。
        """

        events = self.repository.get_events(task_id)

        event = TaskEvent(
            task_id=task_id,
            event_type=event_type,
            node=node,
            payload=payload,
            sequence=len(events) + 1,
        )

        self.repository.append_event(event)
