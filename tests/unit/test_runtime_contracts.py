"""M1 Agent Runtime 契约的组合测试。"""

from uuid import uuid4

import pytest

from repopilot.runtime import (
    AgentRun,
    EventSink,
    FakeBackend,
    InMemoryEventStore,
    ModelRequest,
    ModelResponse,
    RuntimeEvent,
    RuntimeEventType,
    Session,
    Step,
    StepStatus,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultStatus,
    Turn,
    TurnKind,
    TurnStatus,
)
from repopilot.runtime.artifact import Artifact


def test_session_keeps_turn_order_and_rejects_duplicates() -> None:
    """Session 应维护 Turn 顺序，并拒绝重复挂载同一个 Turn。"""

    session = Session(agent_run_id=uuid4())
    turn_id = uuid4()

    session.append_turn(turn_id)

    assert session.turn_ids == (turn_id,)

    with pytest.raises(ValueError):
        session.append_turn(turn_id)


def test_turn_and_step_have_independent_lifecycles() -> None:
    """一个 Turn 可以包含多个 Step，二者状态互不混淆。"""

    turn = Turn(session_id=uuid4(), kind=TurnKind.USER_REQUEST)
    first_step = Step(turn_id=turn.id, sequence=1)

    turn.transition_to(TurnStatus.RUNNING)
    turn.append_step(first_step.id)
    first_step.transition_to(StepStatus.COMPLETED)
    turn.transition_to(TurnStatus.SUCCEEDED)

    assert turn.step_ids == (first_step.id,)
    assert first_step.status is StepStatus.COMPLETED
    assert turn.status is TurnStatus.SUCCEEDED


def test_tool_result_can_represent_unknown_outcome() -> None:
    """工具结果必须能够表达可能已产生副作用但无法确认的情况。"""

    artifact = Artifact(
        kind="log",
        uri="artifact://runs/run-1/log.txt",
        name="tool.log",
    )
    result = ToolResult(
        tool_call_id=uuid4(),
        status=ToolResultStatus.UNKNOWN_OUTCOME,
        error="connection lost after write",
        artifacts=(artifact,),
    )

    assert result.status is ToolResultStatus.UNKNOWN_OUTCOME
    assert result.artifacts == (artifact,)


async def test_fake_backend_records_requests_and_returns_in_order() -> None:
    """FakeBackend 应按预设顺序返回响应，便于测试 Agent Loop。"""

    run = AgentRun(
        task_id=uuid4(),
        backend="fake",
        model="test-model",
    )
    session = Session(agent_run_id=run.id)
    turn = Turn(session_id=session.id, kind=TurnKind.USER_REQUEST)
    step = Step(turn_id=turn.id, sequence=1)
    expected = ModelResponse(
        content=None,
        tool_calls=(
            ToolCall(
                name="read_file",
                arguments={"path": "README.md"},
            ),
        ),
        finish_reason="tool_calls",
    )
    backend = FakeBackend(responses=[expected])
    request = ModelRequest(
        model="test-model",
        session_id=session.id,
        turn_id=turn.id,
        step_id=step.id,
        tools=(
            ToolDefinition(
                name="read_file",
                description="读取一个仓库文件",
            ),
        ),
    )

    response = await backend.complete(request)

    assert backend.backend_name == "fake"
    assert response == expected
    assert backend.requests == [request]


def test_event_store_requires_contiguous_sequences() -> None:
    """事件存储应拒绝跳号，保证后续可以可靠重放事件。"""

    run_id = uuid4()
    store: EventSink = InMemoryEventStore()

    store.append(
        RuntimeEvent(
            agent_run_id=run_id,
            event_type=RuntimeEventType.SESSION_CREATED,
            subject_id=uuid4(),
            sequence=1,
        )
    )

    with pytest.raises(ValueError):
        store.append(
            RuntimeEvent(
                agent_run_id=run_id,
                event_type=RuntimeEventType.STATUS_CHANGED,
                subject_id=run_id,
                sequence=3,
            )
        )

    assert len(store.get_events(run_id)) == 1
