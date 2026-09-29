"""工具调用编排器。

``ToolRegistry`` 只负责找到工具，``ToolOrchestrator`` 负责在真正执行前
依次经过策略和审批。这一层是 ExecutionGateway、Docker 和写工具的固定
入口，避免 HarnessLoop 直接触碰副作用处理器。
"""

from dataclasses import dataclass
from uuid import UUID

from repopilot.harness.approval import (
    ApprovalRequest,
    ApprovalService,
    ApprovalStatus,
)
from repopilot.harness.policy import (
    DefaultPolicyEngine,
    PolicyDecision,
    PolicyEngine,
    ToolPolicyContext,
)
from repopilot.runtime.tool import (
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultStatus,
)
from repopilot.tools.registry import ToolRegistry


@dataclass(frozen=True)
class ToolExecutionOutcome:
    """一次工具编排的结果和可能产生的审批请求。"""

    result: ToolResult
    approval_request: ApprovalRequest | None = None


class ToolOrchestrator:
    """统一执行工具注册、策略、审批和底层处理器。"""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        policy_engine: PolicyEngine | None = None,
        approval_service: ApprovalService | None = None,
    ) -> None:
        self._registry = registry
        self._policy_engine = policy_engine or DefaultPolicyEngine()

        if approval_service is None:
            from repopilot.harness.approval import InMemoryApprovalService

            approval_service = InMemoryApprovalService()
        self._approval_service = approval_service

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """返回模型可见的工具定义。"""

        return self._registry.definitions()

    async def execute(
        self,
        agent_run_id: UUID,
        call: ToolCall,
    ) -> ToolExecutionOutcome:
        """按 Registry → Policy → Approval → Handler 顺序处理 ToolCall。"""

        definition = self._registry.get_definition(call.name)
        if definition is None:
            return ToolExecutionOutcome(
                result=ToolResult(
                    tool_call_id=call.id,
                    status=ToolResultStatus.REJECTED,
                    error=f"Tool '{call.name}' is not registered.",
                )
            )

        evaluation = await self._policy_engine.evaluate(
            ToolPolicyContext(agent_run_id=agent_run_id),
            call,
            definition,
        )

        if evaluation.decision is PolicyDecision.DENY:
            return ToolExecutionOutcome(
                result=ToolResult(
                    tool_call_id=call.id,
                    status=ToolResultStatus.REJECTED,
                    error=evaluation.reason,
                )
            )

        if evaluation.decision is PolicyDecision.REQUIRE_APPROVAL:
            approval = await self._approval_service.request(
                agent_run_id,
                call,
                evaluation.reason,
            )
            return ToolExecutionOutcome(
                result=ToolResult(
                    tool_call_id=call.id,
                    status=ToolResultStatus.APPROVAL_REQUIRED,
                    error=evaluation.reason,
                ),
                approval_request=approval,
            )

        return ToolExecutionOutcome(
            result=await self._registry.execute(call)
        )

    async def resume_approved(
        self,
        agent_run_id: UUID,
        approval_id: UUID,
    ) -> ToolExecutionOutcome:
        """执行一条已经批准的原始 ToolCall，而不是重新让模型猜测动作。"""

        approval = await self._approval_service.get(approval_id)
        if approval.agent_run_id != agent_run_id:
            return ToolExecutionOutcome(
                result=ToolResult(
                    tool_call_id=approval.tool_call.id,
                    status=ToolResultStatus.REJECTED,
                    error="Approval does not belong to this AgentRun.",
                )
            )

        if approval.status is ApprovalStatus.PENDING:
            return ToolExecutionOutcome(
                result=ToolResult(
                    tool_call_id=approval.tool_call.id,
                    status=ToolResultStatus.APPROVAL_REQUIRED,
                    error=approval.reason,
                ),
                approval_request=approval,
            )

        if approval.status is ApprovalStatus.REJECTED:
            return ToolExecutionOutcome(
                result=ToolResult(
                    tool_call_id=approval.tool_call.id,
                    status=ToolResultStatus.REJECTED,
                    error=approval.resolution_reason or "Approval was rejected.",
                )
            )

        return ToolExecutionOutcome(
            result=await self._registry.execute(approval.tool_call)
        )
