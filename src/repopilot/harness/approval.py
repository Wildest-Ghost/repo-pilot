"""工具审批服务的内存实现。

审批等待是 Harness 的一种可恢复状态，不是普通工具失败。本模块只保存
“哪一次 Agent Run 请求批准哪一个 ToolCall”以及批准结果；真正的 UI、数据库
和通知系统属于后续适配器。
"""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from repopilot.runtime.tool import ToolCall


class ApprovalStatus(StrEnum):
    """审批请求的生命周期状态。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalNotFoundError(LookupError):
    """请求的审批记录不存在。"""


class ApprovalAlreadyResolvedError(ValueError):
    """已经处理过的审批请求不能再次处理。"""


@dataclass(frozen=True)
class ApprovalRequest:
    """与原始 ToolCall 绑定的一次审批请求。"""

    agent_run_id: UUID
    tool_call: ToolCall
    reason: str
    id: UUID = field(default_factory=uuid4)
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    resolution_reason: str | None = None


class ApprovalService(Protocol):
    """审批服务的异步端口。"""

    async def request(
        self,
        agent_run_id: UUID,
        tool_call: ToolCall,
        reason: str,
    ) -> ApprovalRequest:
        """创建一个待处理审批请求。"""

        ...

    async def get(self, approval_id: UUID) -> ApprovalRequest:
        """读取一条审批请求。"""

        ...

    async def resolve(
        self,
        approval_id: UUID,
        *,
        approved: bool,
        reason: str | None = None,
    ) -> ApprovalRequest:
        """批准或拒绝一条尚未处理的审批请求。"""

        ...


def _new_approval_map() -> dict[UUID, ApprovalRequest]:
    """创建独立的内存审批记录表。"""

    return {}


@dataclass
class InMemoryApprovalService:
    """用于 M3.2 测试和本地开发的审批服务。"""

    _requests: dict[UUID, ApprovalRequest] = field(
        default_factory=_new_approval_map,
        repr=False,
    )

    async def request(
        self,
        agent_run_id: UUID,
        tool_call: ToolCall,
        reason: str,
    ) -> ApprovalRequest:
        """创建并保存待处理审批请求。"""

        approval = ApprovalRequest(
            agent_run_id=agent_run_id,
            tool_call=tool_call,
            reason=reason,
        )
        self._requests[approval.id] = approval
        return approval

    async def get(self, approval_id: UUID) -> ApprovalRequest:
        """读取审批记录，不存在时明确抛出异常。"""

        try:
            return self._requests[approval_id]
        except KeyError as error:
            raise ApprovalNotFoundError(
                f"Approval '{approval_id}' was not found."
            ) from error

    async def resolve(
        self,
        approval_id: UUID,
        *,
        approved: bool,
        reason: str | None = None,
    ) -> ApprovalRequest:
        """执行一次不可重复的审批决策。"""

        current = await self.get(approval_id)
        if current.status is not ApprovalStatus.PENDING:
            raise ApprovalAlreadyResolvedError(
                f"Approval '{approval_id}' is already resolved."
            )

        resolved = replace(
            current,
            status=(
                ApprovalStatus.APPROVED
                if approved
                else ApprovalStatus.REJECTED
            ),
            resolved_at=datetime.now(UTC),
            resolution_reason=reason,
        )
        self._requests[approval_id] = resolved
        return resolved
