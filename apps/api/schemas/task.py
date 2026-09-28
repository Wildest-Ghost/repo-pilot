"""Task API 的输入输出模型。

Schema 只负责 HTTP 边界的数据校验和序列化，不承载任务状态迁移或
仓储逻辑。
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from repopilot.domain.event import TaskEventType
from repopilot.domain.task import TaskStatus


class TaskCreateRequest(BaseModel):
    """创建 Task 时由客户端提交的最小请求。"""

    instruction: str = Field(
        min_length=1,
        max_length=10_000,
        description="RepoPilot 需要执行的代码任务。",
    )


class TaskResponse(BaseModel):
    """Task 的对外只读表示。"""

    id: UUID
    instruction: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime


class TaskEventResponse(BaseModel):
    """Task 事件的对外只读表示。"""

    task_id: UUID
    event_type: TaskEventType
    node: str
    payload: dict[str, str]
    sequence: int
    occurred_at: datetime
