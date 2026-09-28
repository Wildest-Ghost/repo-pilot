"""Task 持久化端口。

应用服务依赖这个 Protocol，而不是依赖具体的内存或 PostgreSQL 实现。
这使得运行时契约稳定前可以使用内存适配器，后续再替换持久化方案。
"""

from typing import Protocol
from uuid import UUID

from repopilot.domain.event import TaskEvent
from repopilot.domain.task import Task


class TaskRepository(Protocol):
    """Task 与其有序事件的最小存储能力。"""

    def save_task(self, task: Task) -> None:
        """创建或更新一个 Task。"""

        ...

    def get_task(self, task_id: UUID) -> Task | None:
        """按 ID 获取 Task；不存在时返回 None。"""

        ...

    def append_event(self, event: TaskEvent) -> None:
        """追加一条已经分配序号的 Task 事件。"""

        ...

    def get_events(self, task_id: UUID) -> list[TaskEvent]:
        """按追加顺序读取 Task 的事件。"""

        ...
