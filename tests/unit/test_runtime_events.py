"""M3.5 Harness 运行事件和工作区绑定测试。"""

from uuid import uuid4

from repopilot.harness import HarnessLoop, HarnessRunRequest, HarnessStopReason
from repopilot.runtime import (
    AgentRun,
    FakeBackend,
    InMemoryEventStore,
    ModelResponse,
    RuntimeEventType,
    Session,
    Turn,
    TurnKind,
    UserMessage,
)
from repopilot.tools import ToolRegistry


async def test_harness_emits_ordered_model_and_final_status_events() -> None:
    """一次成功运行应写入会话、模型请求、模型响应和终态事实。"""

    run = AgentRun(
        task_id=uuid4(),
        backend="fake",
        model="test-model",
        workspace_root="D:/workspace/repo-1",
    )
    session = Session(agent_run_id=run.id)
    turn = Turn(session_id=session.id, kind=TurnKind.USER_REQUEST)
    events = InMemoryEventStore()
    result = await HarnessLoop(
        backend=FakeBackend([ModelResponse(content="done")]),
        tool_registry=ToolRegistry(),
        event_sink=events,
    ).run(
        HarnessRunRequest(
            agent_run=run,
            session=session,
            turn=turn,
            model=run.model,
            messages=(UserMessage(content="inspect"),),
        )
    )

    assert result.stop_reason is HarnessStopReason.COMPLETED
    recorded = events.get_events(run.id)
    assert [event.sequence for event in recorded] == list(
        range(1, len(recorded) + 1)
    )
    event_types = [event.event_type for event in recorded]
    assert RuntimeEventType.SESSION_CREATED in event_types
    assert RuntimeEventType.TURN_CREATED in event_types
    assert RuntimeEventType.MODEL_REQUESTED in event_types
    assert RuntimeEventType.MODEL_RESPONDED in event_types
    assert event_types[-1] is RuntimeEventType.STATUS_CHANGED
    session_event = next(
        event
        for event in recorded
        if event.event_type is RuntimeEventType.SESSION_CREATED
    )
    assert session_event.payload["workspace_root"] == "D:/workspace/repo-1"
