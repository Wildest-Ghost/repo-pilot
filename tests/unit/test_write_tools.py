"""M3.3 write_file 工具的审批和执行闭环测试。"""

from collections.abc import Mapping
from pathlib import Path
from typing import cast
from uuid import uuid4

from repopilot.execution import LocalExecutionGateway
from repopilot.harness import (
    ApprovalStatus,
    InMemoryApprovalService,
    ToolOrchestrator,
)
from repopilot.runtime import ToolCall, ToolResultStatus
from repopilot.tools import ToolRegistry, register_write_tools


def make_write_orchestrator(
    root: Path,
) -> tuple[ToolOrchestrator, InMemoryApprovalService]:
    """创建使用本地执行网关和内存审批的写工具编排器。"""

    registry = ToolRegistry()
    register_write_tools(registry, LocalExecutionGateway(root))
    approvals = InMemoryApprovalService()
    return (
        ToolOrchestrator(registry, approval_service=approvals),
        approvals,
    )


async def test_write_file_requires_approval_and_writes_after_resume(
    tmp_path: Path,
) -> None:
    """审批前文件不变，批准原始调用后才写入文件。"""

    orchestrator, approvals = make_write_orchestrator(tmp_path)
    run_id = uuid4()
    call = ToolCall(
        name="write_file",
        arguments={
            "path": "src/app.py",
            "content": "answer = 42\n",
            "create_parent_dirs": True,
        },
    )

    pending = await orchestrator.execute(run_id, call)
    assert pending.result.status is ToolResultStatus.APPROVAL_REQUIRED
    assert pending.approval_request is not None
    assert pending.approval_request.status is ApprovalStatus.PENDING
    assert not (tmp_path / "src" / "app.py").exists()

    await approvals.resolve(pending.approval_request.id, approved=True)
    completed = await orchestrator.resume_approved(
        run_id,
        pending.approval_request.id,
    )

    assert completed.result.status is ToolResultStatus.COMPLETED
    output = cast(Mapping[str, object] | None, completed.result.output)
    assert output is not None
    assert output["path"] == "src/app.py"
    assert (tmp_path / "src" / "app.py").read_text(encoding="utf-8") == (
        "answer = 42\n"
    )


async def test_rejected_write_file_never_changes_workspace(tmp_path: Path) -> None:
    """拒绝审批后，原始写入动作不能执行。"""

    orchestrator, approvals = make_write_orchestrator(tmp_path)
    run_id = uuid4()
    pending = await orchestrator.execute(
        run_id,
        ToolCall(
            name="write_file",
            arguments={"path": "app.py", "content": "pass"},
        ),
    )
    assert pending.approval_request is not None

    await approvals.resolve(
        pending.approval_request.id,
        approved=False,
        reason="用户拒绝修改",
    )
    rejected = await orchestrator.resume_approved(
        run_id,
        pending.approval_request.id,
    )

    assert rejected.result.status is ToolResultStatus.REJECTED
    assert "用户拒绝修改" in (rejected.result.error or "")
    assert not (tmp_path / "app.py").exists()


async def test_write_file_validates_arguments_before_gateway_call(
    tmp_path: Path,
) -> None:
    """工具参数类型错误应被标准化为失败结果。"""

    orchestrator, approvals = make_write_orchestrator(tmp_path)
    run_id = uuid4()
    pending = await orchestrator.execute(
        run_id,
        ToolCall(
            name="write_file",
            arguments={"path": "app.py", "content": "pass"},
        ),
    )
    assert pending.approval_request is not None
    await approvals.resolve(pending.approval_request.id, approved=True)

    # handler 参数校验发生在批准后、真正写文件前。
    invalid = await orchestrator.execute(
        run_id,
        ToolCall(
            name="write_file",
            arguments={"path": "bad.py", "content": 123},
        ),
    )
    assert invalid.approval_request is not None
    await approvals.resolve(invalid.approval_request.id, approved=True)
    failed = await orchestrator.resume_approved(
        run_id,
        invalid.approval_request.id,
    )

    assert failed.result.status is ToolResultStatus.FAILED
    assert "content must be a string" in (failed.result.error or "")
    assert not (tmp_path / "bad.py").exists()
