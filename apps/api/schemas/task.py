from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field
from repopilot.domain.event import TaskEventType
from repopilot.domain.task import TaskStatus


class TaskCreateRequest(BaseModel):
    instruction: str = Field(
        min_length=1,
        max_length=10_000,
        description="The coding task for RepoPilot to execute.",
    )


class TaskResponse(BaseModel):
    id: UUID
    instruction: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime

class TaskEventResponse(BaseModel):
    task_id: UUID
    event_type: TaskEventType
    node: str
    payload: dict[str, str]
    sequence: int
    occurred_at: datetime