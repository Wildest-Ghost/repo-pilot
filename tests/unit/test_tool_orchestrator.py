"""M3.2 工具编排、策略和审批状态测试。"""

from collections.abc import Awaitable, Callable, Mapping
from uuid import uuid4

import pytest

from repopilot.harness import (
    ApprovalAlreadyResolvedError,
    ApprovalStatus,
    DefaultPolicyEngine,
    InMemoryApprovalService,
    ToolOrchestrator,
)
from repopilot.runtime import ToolCall, ToolDefinition, ToolResultStatus
from repopilot.tools import ToolRegistry


def make_registry(
    *,
    read_only: bool,
    handler: Callable[[Mapping[str, object]], Awaitable[object]],
) -> ToolRegistry:
    """创建一个用于策略测试的单工具注册表。"""

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="write_file" if not read_only else "read_file",
            description="测试工具",
            read_only=read_only,
        ),
        handler,
    )
    return registry


async def test_read_only_tool_is_allowed_and_executed() -> None:
    """只读工具应经过策略后直接执行。"""

    calls: list[Mapping[str, object]] = []

    async def handler(arguments: Mapping[str, object]) -> object:
        calls.append(arguments)
        return {"ok": True}

    orchestrator = ToolOrchestrator(
        make_registry(read_only=True, handler=handler)
    )
    outcome = await orchestrator.execute(
        uuid4(),
        ToolCall(name="read_file", arguments={"path": "README.md"}),
    )

    assert outcome.result.status is ToolResultStatus.COMPLETED
    assert outcome.result.output == {"ok": True}
    assert outcome.approval_request is None
    assert calls == [{"path": "README.md"}]


async def test_side_effect_tool_requires_approval_before_handler() -> None:
    """副作用工具在审批前不能触发底层处理器。"""

    called = False

    async def handler(_: Mapping[str, object]) -> object:
        nonlocal called
        called = True
        return "should not execute"

    approval_service = InMemoryApprovalService()
    orchestrator = ToolOrchestrator(
        make_registry(read_only=False, handler=handler),
        approval_service=approval_service,
    )
    run_id = uuid4()
    outcome = await orchestrator.execute(
        run_id,
        ToolCall(name="write_file", arguments={"path": "app.py"}),
    )

    assert outcome.result.status is ToolResultStatus.APPROVAL_REQUIRED
    assert outcome.approval_request is not None
    assert outcome.approval_request.agent_run_id == run_id
    assert outcome.approval_request.status is ApprovalStatus.PENDING
    assert called is False


async def test_denied_tool_is_rejected_without_approval() -> None:
    """策略明确拒绝时不能创建审批，也不能执行工具。"""

    async def handler(_: Mapping[str, object]) -> object:
        return "should not execute"

    orchestrator = ToolOrchestrator(
        make_registry(read_only=True, handler=handler),
        policy_engine=DefaultPolicyEngine(
            denied_tools=frozenset({"read_file"})
        ),
    )
    outcome = await orchestrator.execute(uuid4(), ToolCall(name="read_file"))

    assert outcome.result.status is ToolResultStatus.REJECTED
    assert outcome.result.error is not None
    assert "denied" in outcome.result.error
    assert outcome.approval_request is None


async def test_approved_call_resumes_original_tool_call_once() -> None:
    """批准后应执行原始 ToolCall，重复处理审批必须失败。"""

    received: list[Mapping[str, object]] = []

    async def handler(arguments: Mapping[str, object]) -> object:
        received.append(arguments)
        return {"written": True}

    approval_service = InMemoryApprovalService()
    orchestrator = ToolOrchestrator(
        make_registry(read_only=False, handler=handler),
        approval_service=approval_service,
    )
    run_id = uuid4()
    first = await orchestrator.execute(
        run_id,
        ToolCall(name="write_file", arguments={"path": "app.py"}),
    )
    assert first.approval_request is not None

    approval_id = first.approval_request.id
    await approval_service.resolve(approval_id, approved=True)
    resumed = await orchestrator.resume_approved(run_id, approval_id)

    assert resumed.result.status is ToolResultStatus.COMPLETED
    assert resumed.result.output == {"written": True}
    assert received == [{"path": "app.py"}]

    with pytest.raises(ApprovalAlreadyResolvedError):
        await approval_service.resolve(approval_id, approved=False)
