"""Task 聚合及其状态迁移规则。

Task 只维护自身不变量和合法状态迁移，不直接依赖 API、数据库或
Agent Runtime。这样后续接入 Harness 时，任务生命周期仍有单一事实来源。
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID, uuid4


class TaskStatus(StrEnum):
    """Task 在当前最小生命周期中的状态集合。"""

    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvalidTaskTransitionError(ValueError):
    """Task 尝试执行不允许的状态迁移时抛出。"""


@dataclass
class Task:
    """代表一个待由 RepoPilot 处理的代码仓库任务。"""

    instruction: str
    id: UUID = field(default_factory=uuid4)
    status: TaskStatus = TaskStatus.CREATED
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    _ALLOWED_TRANSITIONS: ClassVar[dict[TaskStatus, frozenset[TaskStatus]]] = {
        # 状态迁移集中声明，避免 API 或服务层各自复制一套规则。
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
        """规范化任务描述，并拒绝空白任务。"""

        self.instruction = self.instruction.strip()

        if not self.instruction:
            raise ValueError("Task instruction must not be empty.")

    def transition_to(self, target_status: TaskStatus) -> None:
        """执行一次受约束的状态迁移，并刷新更新时间。"""

        allowed_statuses = self._ALLOWED_TRANSITIONS[self.status]

        if target_status not in allowed_statuses:
            raise InvalidTaskTransitionError(
                f"Cannot transition task from '{self.status.value}' "
                f"to '{target_status.value}'."
            )

        self.status = target_status
        self.updated_at = datetime.now(UTC)
