from uuid import UUID

from fastapi import FastAPI, HTTPException, status
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from repopilot.infra.database import init_db
from repopilot.infra.repositories.postgres import PostgresTaskRepository

from apps.api.schemas.task import (
    TaskCreateRequest,
    TaskEventResponse,
    TaskResponse,
)
from repopilot.domain.task import InvalidTaskTransitionError, Task
from repopilot.services.task_service import TaskNotFoundError, TaskService

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(
    title="RepoPilot API",
    version="0.1.0",
    lifespan=lifespan,
)

task_service = TaskService(
    repository=PostgresTaskRepository(),
)


def to_task_response(task: Task) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        instruction=task.instruction,
        status=task.status,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/v1/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(payload: TaskCreateRequest) -> TaskResponse:
    task = task_service.create_task(instruction=payload.instruction)
    return to_task_response(task)


@app.get("/api/v1/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID) -> TaskResponse:
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