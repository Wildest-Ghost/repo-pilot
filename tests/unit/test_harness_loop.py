"""M2 HarnessLoop 的异步循环和治理限制测试。"""

import asyncio
from collections.abc import Mapping
from uuid import uuid4

from repopilot.harness import (
    ApprovalStatus,
    HarnessLoop,
    HarnessRunRequest,
    HarnessStopReason,
)
from repopilot.runtime import (
    AgentRun,
    AgentRunStatus,
    AssistantMessage,
    FakeBackend,
    ModelResponse,
    Session,
    ToolCall,
    ToolResultStatus,
    Turn,
    TurnKind,
    TurnStatus,
    UserMessage,
)
from repopilot.runtime.tool import ToolDefinition
from repopilot.tools import ToolRegistry


def make_request(
    run: AgentRun,
    session: Session,
    turn: Turn,
    *,
    max_steps: int = 10,
    token_budget: int | None = None,
    timeout_seconds: float | None = None,
    cancel_event: asyncio.Event | None = None,
) -> HarnessRunRequest:
    """构造测试用 HarnessRunRequest。"""

    return HarnessRunRequest(
        agent_run=run,
        session=session,
        turn=turn,
        model=run.model,
        messages=(UserMessage(content="inspect the repository"),),
        max_steps=max_steps,
        token_budget=token_budget,
        timeout_seconds=timeout_seconds,
        cancel_event=cancel_event,
    )


def make_runtime() -> tuple[AgentRun, Session, Turn]:
    """创建一组相互关联的运行时对象。"""

    run = AgentRun(
        task_id=uuid4(),
        backend="fake",
        model="test-model",
    )
    session = Session(agent_run_id=run.id)
    turn = Turn(session_id=session.id, kind=TurnKind.USER_REQUEST)
    return run, session, turn


async def test_harness_loop_completes_without_tool_call() -> None:
    """模型直接返回文本时，HarnessLoop 应成功结束。"""

    run, session, turn = make_runtime()
    backend = FakeBackend(
        responses=[
            ModelResponse(
                content="repository looks healthy",
                usage={"total_tokens": 7},
            )
        ]
    )

    result = await HarnessLoop(
        backend=backend,
        tool_registry=ToolRegistry(),
    ).run(make_request(run, session, turn))

    assert result.stop_reason is HarnessStopReason.COMPLETED
    assert result.run_status is run.status
    assert result.turn_status is turn.status
    assert result.total_tokens == 7
    assert len(result.steps) == 1
    assert isinstance(result.messages[-1], AssistantMessage)


async def test_harness_loop_executes_tool_and_returns_result_to_model() -> None:
    """模型请求只读工具后，工具结果应进入下一次模型上下文。"""

    run, session, turn = make_runtime()
    registry = ToolRegistry()

    async def read_file(arguments: Mapping[str, object]) -> object:
        return {"path": arguments["path"], "content": "hello"}

    registry.register(
        ToolDefinition(
            name="read_file",
            description="读取文件",
        ),
        read_file,
    )
    backend = FakeBackend(
        responses=[
            ModelResponse(
                content=None,
                tool_calls=(
                    ToolCall(
                        name="read_file",
                        arguments={"path": "README.md"},
                    ),
                ),
                finish_reason="tool_calls",
            ),
            ModelResponse(content="file inspected"),
        ]
    )

    result = await HarnessLoop(
        backend=backend,
        tool_registry=registry,
    ).run(make_request(run, session, turn))

    assert result.stop_reason is HarnessStopReason.COMPLETED
    assert len(result.tool_results) == 1
    assert result.tool_results[0].status is ToolResultStatus.COMPLETED
    assert len(backend.requests) == 2
    assert len(backend.requests[1].messages) == 3


async def test_harness_loop_stops_at_max_steps() -> None:
    """模型持续请求工具时，循环不能超过最大步骤。"""

    run, session, turn = make_runtime()
    registry = ToolRegistry()

    async def inspect(arguments: Mapping[str, object]) -> object:
        return {"ok": True}

    registry.register(
        ToolDefinition(name="inspect", description="执行只读检查"),
        inspect,
    )
    backend = FakeBackend(
        responses=[
            ModelResponse(
                content=None,
                tool_calls=(ToolCall(name="inspect"),),
                finish_reason="tool_calls",
            ),
            ModelResponse(
                content=None,
                tool_calls=(ToolCall(name="inspect"),),
                finish_reason="tool_calls",
            ),
        ]
    )

    result = await HarnessLoop(
        backend=backend,
        tool_registry=registry,
    ).run(make_request(run, session, turn, max_steps=2))

    assert result.stop_reason is HarnessStopReason.MAX_STEPS_EXCEEDED
    assert result.run_status is run.status
    assert len(result.steps) == 2


async def test_harness_loop_stops_when_token_budget_is_exceeded() -> None:
    """模型响应累计 Token 超过预算时，运行应失败终止。"""

    run, session, turn = make_runtime()
    backend = FakeBackend(
        responses=[
            ModelResponse(
                content="too expensive",
                usage={"total_tokens": 11},
            )
        ]
    )

    result = await HarnessLoop(
        backend=backend,
        tool_registry=ToolRegistry(),
    ).run(make_request(run, session, turn, token_budget=10))

    assert result.stop_reason is HarnessStopReason.TOKEN_BUDGET_EXCEEDED
    assert result.run_status.value == "failed"
    assert result.total_tokens == 11


async def test_harness_loop_can_be_cancelled_before_next_step() -> None:
    """取消事件被设置后，HarnessLoop 应返回 CANCELLED。"""

    run, session, turn = make_runtime()
    cancel_event = asyncio.Event()
    cancel_event.set()
    backend = FakeBackend(
        responses=[ModelResponse(content="should not be called")]
    )

    result = await HarnessLoop(
        backend=backend,
        tool_registry=ToolRegistry(),
    ).run(
        make_request(
            run,
            session,
            turn,
            cancel_event=cancel_event,
        )
    )

    assert result.stop_reason is HarnessStopReason.CANCELLED
    assert not backend.requests


async def test_harness_loop_waits_for_side_effect_approval() -> None:
    """副作用工具调用应暂停运行并返回可恢复审批请求。"""

    run, session, turn = make_runtime()
    registry = ToolRegistry()
    called = False

    async def write_file(_: Mapping[str, object]) -> object:
        nonlocal called
        called = True
        return {"written": True}

    registry.register(
        ToolDefinition(
            name="write_file",
            description="写入文件",
            read_only=False,
        ),
        write_file,
    )
    backend = FakeBackend(
        responses=[
            ModelResponse(
                content=None,
                tool_calls=(ToolCall(name="write_file"),),
                finish_reason="tool_calls",
            )
        ]
    )

    result = await HarnessLoop(
        backend=backend,
        tool_registry=registry,
    ).run(make_request(run, session, turn))

    assert result.stop_reason is HarnessStopReason.WAITING_APPROVAL
    assert result.run_status is AgentRunStatus.WAITING_APPROVAL
    assert result.turn_status is TurnStatus.WAITING_APPROVAL
    assert result.approval_request is not None
    assert result.approval_request.status is ApprovalStatus.PENDING
    assert result.tool_results[0].status is ToolResultStatus.APPROVAL_REQUIRED
    assert called is False
