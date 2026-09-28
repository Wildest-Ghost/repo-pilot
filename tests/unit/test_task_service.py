"""Task 应用服务的领域行为测试。"""

from uuid import uuid4

import pytest

from repopilot.domain.task import InvalidTaskTransitionError, TaskStatus
from repopilot.services.task_service import TaskService


def test_task_lifecycle_records_ordered_events() -> None:
    """创建并排队后，应留下连续且有序的生命周期事件。"""

    service = TaskService()

    task = service.create_task("  inspect the repository  ")
    queued = service.queue_task(task.id)

    assert queued.status is TaskStatus.QUEUED
    assert [event.event_type.value for event in service.get_events(task.id)] == [
        "task.created",
        "task.queued",
    ]
    assert [event.sequence for event in service.get_events(task.id)] == [1, 2]


def test_unknown_task_is_reported() -> None:
    """查询不存在的 Task 时，应返回明确的领域异常。"""

    service = TaskService()

    with pytest.raises(LookupError):
        service.get_task(uuid4())


def test_invalid_transition_is_rejected() -> None:
    """领域对象应拒绝绕过合法生命周期的状态迁移。"""

    service = TaskService()
    task = service.create_task("inspect the repository")

    with pytest.raises(InvalidTaskTransitionError):
        task.transition_to(TaskStatus.SUCCEEDED)
