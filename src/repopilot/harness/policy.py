"""工具调用策略契约。

策略层只回答一个问题：当前 Tool Call 是允许、拒绝，还是需要人工审批。
它不执行工具，也不负责保存审批记录。这样策略规则可以独立测试，并在
未来根据 TaskSpec、工作区和用户身份扩展，而不污染 ToolRegistry。
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from repopilot.runtime.tool import ToolCall, ToolDefinition


class PolicyDecision(StrEnum):
    """策略引擎对一次工具调用的三种结论。"""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class ToolPolicyContext:
    """策略判断所需的最小运行上下文。"""

    agent_run_id: UUID


@dataclass(frozen=True)
class PolicyEvaluation:
    """一次策略判断的结构化结果。"""

    decision: PolicyDecision
    reason: str


class PolicyEngine(Protocol):
    """策略引擎的异步端口。"""

    async def evaluate(
        self,
        context: ToolPolicyContext,
        call: ToolCall,
        definition: ToolDefinition,
    ) -> PolicyEvaluation:
        """判断一次工具调用能否进入执行阶段。"""

        ...


@dataclass(frozen=True)
class DefaultPolicyEngine:
    """M3.2 的最小默认策略。

    只读工具默认允许；副作用工具默认需要审批；显式列入拒绝集合的工具
    无论是否只读都拒绝。集合是不可变的，避免运行过程中被悄悄修改。
    """

    denied_tools: frozenset[str] = frozenset()

    async def evaluate(
        self,
        context: ToolPolicyContext,
        call: ToolCall,
        definition: ToolDefinition,
    ) -> PolicyEvaluation:
        """按工具风险等级返回策略结论。"""

        del context

        if definition.name in self.denied_tools:
            return PolicyEvaluation(
                decision=PolicyDecision.DENY,
                reason=f"Tool '{call.name}' is denied by policy.",
            )

        if not definition.read_only:
            return PolicyEvaluation(
                decision=PolicyDecision.REQUIRE_APPROVAL,
                reason=f"Tool '{call.name}' requires approval before execution.",
            )

        return PolicyEvaluation(
            decision=PolicyDecision.ALLOW,
            reason=f"Tool '{call.name}' is read-only and allowed.",
        )


PolicyEvaluator = Callable[
    [ToolPolicyContext, ToolCall, ToolDefinition],
    Awaitable[PolicyEvaluation],
]


def policy_engine_from_callable(evaluator: PolicyEvaluator) -> PolicyEngine:
    """将简单异步函数包装成策略引擎，方便测试和实验性策略接入。"""

    class CallablePolicyEngine:
        async def evaluate(
            self,
            context: ToolPolicyContext,
            call: ToolCall,
            definition: ToolDefinition,
        ) -> PolicyEvaluation:
            return await evaluator(context, call, definition)

    return CallablePolicyEngine()
