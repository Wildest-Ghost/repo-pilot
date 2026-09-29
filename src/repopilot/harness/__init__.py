"""Control Harness 的策略、审批与生命周期协调边界。

在运行时契约冻结前，本包有意保持精简。策略、预算、审批、验证和任务
终结属于 Harness；模型提供方和进程执行则必须隐藏在独立端口之后。
"""

from repopilot.harness.approval import (
    ApprovalAlreadyResolvedError,
    ApprovalNotFoundError,
    ApprovalRequest,
    ApprovalService,
    ApprovalStatus,
    InMemoryApprovalService,
)
from repopilot.harness.loop import (
    HarnessLoop,
    HarnessRunRequest,
    HarnessRunResult,
    HarnessStopReason,
)
from repopilot.harness.orchestrator import (
    ToolExecutionOutcome,
    ToolOrchestrator,
)
from repopilot.harness.policy import (
    DefaultPolicyEngine,
    PolicyDecision,
    PolicyEngine,
    PolicyEvaluation,
    ToolPolicyContext,
)

__all__ = [
    "ApprovalAlreadyResolvedError",
    "ApprovalNotFoundError",
    "ApprovalRequest",
    "ApprovalService",
    "ApprovalStatus",
    "DefaultPolicyEngine",
    "HarnessLoop",
    "HarnessRunRequest",
    "HarnessRunResult",
    "HarnessStopReason",
    "InMemoryApprovalService",
    "PolicyDecision",
    "PolicyEngine",
    "PolicyEvaluation",
    "ToolExecutionOutcome",
    "ToolOrchestrator",
    "ToolPolicyContext",
]
