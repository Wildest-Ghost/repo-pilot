"""RepoPilot 的 FastAPI 入口。

本模块只负责 HTTP 协议适配：解析请求、调用应用服务并映射异常。
任务状态机和事件追加仍由 domain 与 services 层负责。
"""

from uuid import UUID

from fastapi import FastAPI, HTTPException, status

from apps.api.schemas.task import (
    TaskCreateRequest,
    TaskEventResponse,
    TaskResponse,
)
from repopilot.domain.task import InvalidTaskTransitionError, Task
from repopilot.infra.repositories.in_memory import InMemoryTaskRepository
from repopilot.services.task_service import TaskNotFoundError, TaskService

app = FastAPI(
    title="RepoPilot API",
    version="0.1.0",
)

task_service = TaskService(
    # 第一阶段让 API 与存储实现解耦；事件契约稳定后再接入 PostgreSQL。
    repository=InMemoryTaskRepository(),
)


def to_task_response(task: Task) -> TaskResponse:
    """将领域对象转换为不暴露内部实现的 HTTP 响应。"""

    return TaskResponse(
        id=task.id,
        instruction=task.instruction,
        status=task.status,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@app.get("/health")
async def health_check() -> dict[str, str]:
    """返回进程级健康状态，供部署探针使用。"""

    return {"status": "ok"}


@app.post(
    "/api/v1/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(payload: TaskCreateRequest) -> TaskResponse:
    """创建 Task，并返回初始的 CREATED 状态。"""

    task = task_service.create_task(instruction=payload.instruction)
    return to_task_response(task)


@app.get("/api/v1/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID) -> TaskResponse:
    """按 ID 查询 Task；不存在时映射为 HTTP 404。"""

    try:
        task = task_service.get_task(task_id)
    except TaskNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return to_task_response(task)


@app.post(
    "/api/v1/tasks/{task_id}/queue",
    response_model=TaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def queue_task(task_id: UUID) -> TaskResponse:
    """将 Task 放入队列；非法状态迁移映射为 HTTP 409。"""

    try:
        task = task_service.queue_task(task_id)
    except TaskNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except InvalidTaskTransitionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    return to_task_response(task)


@app.get(
    "/api/v1/tasks/{task_id}/events",
    response_model=list[TaskEventResponse],
)
async def get_task_events(task_id: UUID) -> list[TaskEventResponse]:
    """返回 Task 的有序事件流；未知 Task 映射为 HTTP 404。"""

    try:
        events = task_service.get_events(task_id)
    except TaskNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return [
        TaskEventResponse(
            task_id=event.task_id,
            event_type=event.event_type,
            node=event.node,
            payload=event.payload,
            sequence=event.sequence,
            occurred_at=event.occurred_at,
        )
        for event in events
    ]
