"""TaskRepository 的 PostgreSQL 适配器原型。

该模块实现了持久化接口，但当前 API 仍使用内存仓库。只有在事件契约、
迁移策略和恢复测试稳定后，才应将它接入默认运行路径。
"""

from uuid import UUID

from sqlalchemy import select

from repopilot.domain.event import TaskEvent, TaskEventType
from repopilot.domain.task import Task, TaskStatus
from repopilot.infra.database import SessionLocal
from repopilot.infra.models import TaskEventModel, TaskModel
from repopilot.services.task_repository import TaskRepository


class PostgresTaskRepository(TaskRepository):
    """使用 SQLAlchemy Session 管理 Task 和 TaskEvent 的仓库。"""

    def save_task(self, task: Task) -> None:
        """在一个事务中创建或更新 Task。"""

        with SessionLocal.begin() as session:
            model = session.get(TaskModel, task.id)

            if model is None:
                session.add(
                    TaskModel(
                        id=task.id,
                        instruction=task.instruction,
                        status=task.status.value,
                        created_at=task.created_at,
                        updated_at=task.updated_at,
                    )
                )
                return

            model.instruction = task.instruction
            model.status = task.status.value
            model.updated_at = task.updated_at

    def get_task(self, task_id: UUID) -> Task | None:
        """读取 Task，并将持久化模型还原为领域对象。"""

        with SessionLocal() as session:
            model = session.get(TaskModel, task_id)

            if model is None:
                return None

            return Task(
                id=model.id,
                instruction=model.instruction,
                status=TaskStatus(model.status),
                created_at=model.created_at,
                updated_at=model.updated_at,
            )

    def append_event(self, event: TaskEvent) -> None:
        """在一个事务中追加已经分配序号的事件。"""

        with SessionLocal.begin() as session:
            session.add(
                TaskEventModel(
                    task_id=event.task_id,
                    sequence=event.sequence,
                    event_type=event.event_type.value,
                    node=event.node,
                    payload=event.payload,
                    occurred_at=event.occurred_at,
                )
            )

    def get_events(self, task_id: UUID) -> list[TaskEvent]:
        """按 sequence 升序读取事件并还原为领域事件。"""

        statement = (
            select(TaskEventModel)
            .where(TaskEventModel.task_id == task_id)
            .order_by(TaskEventModel.sequence)
        )

        with SessionLocal() as session:
            models = session.scalars(statement).all()

            return [
                TaskEvent(
                    task_id=model.task_id,
                    event_type=TaskEventType(model.event_type),
                    node=model.node,
                    payload=model.payload,
                    sequence=model.sequence,
                    occurred_at=model.occurred_at,
                )
                for model in models
            ]
