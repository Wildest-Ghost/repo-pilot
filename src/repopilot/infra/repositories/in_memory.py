"""TaskRepository 的进程内实现。

内存仓库用于当前早期阶段的 API 和单元测试。它不提供跨进程持久化，
也不承担并发事件序号分配；这些能力留给后续的持久化适配器。
"""

from dataclasses import dataclass, field
from uuid import UUID

from repopilot.domain.event import TaskEvent
from repopilot.domain.task import Task
from repopilot.services.task_repository import TaskRepository


def _new_task_map() -> dict[UUID, Task]:
    """为 dataclass 创建独立的 Task 字典，避免共享可变默认值。"""

    return {}


def _new_event_map() -> dict[UUID, list[TaskEvent]]:
    """为 dataclass 创建独立的事件字典，避免共享可变默认值。"""

    return {}


@dataclass
class InMemoryTaskRepository(TaskRepository):
    """保存 Task 和其事件序列的内存仓库。"""

    _tasks: dict[UUID, Task] = field(default_factory=_new_task_map)
    _events: dict[UUID, list[TaskEvent]] = field(default_factory=_new_event_map)

    def save_task(self, task: Task) -> None:
        """创建或覆盖一个 Task，并确保它拥有事件列表。"""

        self._tasks[task.id] = task
        self._events.setdefault(task.id, [])

    def get_task(self, task_id: UUID) -> Task | None:
        """按 ID 获取 Task，不存在时返回 None。"""

        return self._tasks.get(task_id)

    def append_event(self, event: TaskEvent) -> None:
        """追加事件；调用方负责保证 Task 已先保存。"""

        self._events[event.task_id].append(event)

    def get_events(self, task_id: UUID) -> list[TaskEvent]:
        """返回事件列表的浅拷贝，避免调用方直接修改仓库内部列表。"""

        return list(self._events.get(task_id, []))
