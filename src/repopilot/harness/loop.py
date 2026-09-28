"""最小异步 HarnessLoop。

M2 的循环只支持只读工具。它负责：

* 向 AgentBackend 发起模型请求；
* 识别模型是否返回 ToolCall；
* 通过 ToolRegistry 执行已注册工具；
* 将 ToolResult 作为内部 ToolMessage 放回上下文；
* 应用步骤、工具调用、Token、超时和取消限制。

写工具、审批、Docker 沙箱和真实 DeepSeekBackend 放在 M3。
"""

import asyncio
from dataclasses import dataclass
from enum import StrEnum

from repopilot.runtime.backend import AgentBackend, ModelRequest
from repopilot.runtime.messages import (
    AssistantMessage,
    Message,
    ToolMessage,
)
from repopilot.runtime.run import AgentRun, AgentRunStatus
from repopilot.runtime.session import (
    Session,
    Step,
    StepStatus,
    Turn,
    TurnStatus,
)
from repopilot.runtime.tool import ToolResult
from repopilot.tools.registry import ToolRegistry


class HarnessStopReason(StrEnum):
    """一次 HarnessLoop 结束的原因。"""

    COMPLETED = "completed"
    MAX_STEPS_EXCEEDED = "max_steps_exceeded"
    TOOL_CALL_LIMIT_EXCEEDED = "tool_call_limit_exceeded"
    TOKEN_BUDGET_EXCEEDED = "token_budget_exceeded"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    MODEL_ERROR = "model_error"
    EMPTY_RESPONSE = "empty_response"


@dataclass(frozen=True)
class HarnessRunRequest:
    """启动一次最小 HarnessLoop 所需的输入和限制。"""

    agent_run: AgentRun
    session: Session
    turn: Turn
    model: str
    messages: tuple[Message, ...]
    max_steps: int = 10
    max_tool_calls: int = 32
    token_budget: int | None = None
    timeout_seconds: float | None = None
    cancel_event: asyncio.Event | None = None

    def __post_init__(self) -> None:
        """拒绝无效的运行限制，避免循环无法终止。"""

        if self.max_steps <= 0:
            raise ValueError("max_steps must be positive.")

        if self.max_tool_calls <= 0:
            raise ValueError("max_tool_calls must be positive.")

        if self.token_budget is not None and self.token_budget <= 0:
            raise ValueError("token_budget must be positive.")

        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")


@dataclass(frozen=True)
class HarnessRunResult:
    """HarnessLoop 的可审计结果摘要。"""

    run_status: AgentRunStatus
    turn_status: TurnStatus
    stop_reason: HarnessStopReason
    messages: tuple[Message, ...]
    tool_results: tuple[ToolResult, ...]
    steps: tuple[Step, ...]
    total_tokens: int


class HarnessLoop:
    """在模型和只读工具之间驱动一次异步执行循环。"""

    def __init__(
        self,
        backend: AgentBackend,
        tool_registry: ToolRegistry,
    ) -> None:
        self._backend = backend
        self._tool_registry = tool_registry

    async def run(self, request: HarnessRunRequest) -> HarnessRunResult:
        """执行一次受步骤、Token、时间和取消约束的 Agent Run。"""

        self._start_run(request)

        try:
            if request.timeout_seconds is None:
                return await self._run_without_timeout(request)

            async with asyncio.timeout(request.timeout_seconds):
                return await self._run_without_timeout(request)
        except TimeoutError:
            return self._failed_result(
                request,
                HarnessStopReason.TIMEOUT,
                messages=request.messages,
            )
        except asyncio.CancelledError:
            self._cancel_run(request)
            raise
        except Exception:
            return self._failed_result(
                request,
                HarnessStopReason.MODEL_ERROR,
                messages=request.messages,
            )

    async def _run_without_timeout(
        self,
        request: HarnessRunRequest,
    ) -> HarnessRunResult:
        messages = list(request.messages)
        tool_results: list[ToolResult] = []
        steps: list[Step] = []
        total_tokens = 0

        if request.turn.id not in request.session.turn_ids:
            request.session.append_turn(request.turn.id)

        for sequence in range(1, request.max_steps + 1):
            if self._is_cancelled(request):
                return self._cancelled_result(
                    request,
                    messages,
                    tool_results,
                    steps,
                    total_tokens,
                )

            step = Step(turn_id=request.turn.id, sequence=sequence)
            request.turn.append_step(step.id)
            steps.append(step)

            model_request = ModelRequest(
                model=request.model,
                session_id=request.session.id,
                turn_id=request.turn.id,
                step_id=step.id,
                messages=tuple(messages),
                tools=self._tool_registry.definitions(),
            )
            response = await self._backend.complete(model_request)
            total_tokens += response.usage.get("total_tokens", 0)
            messages.append(
                AssistantMessage(
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )
            step.transition_to(StepStatus.COMPLETED)

            if (
                request.token_budget is not None
                and total_tokens > request.token_budget
            ):
                return self._failed_result(
                    request,
                    HarnessStopReason.TOKEN_BUDGET_EXCEEDED,
                    messages,
                    tool_results,
                    steps,
                    total_tokens,
                )

            if not response.tool_calls:
                if not response.content:
                    return self._failed_result(
                        request,
                        HarnessStopReason.EMPTY_RESPONSE,
                        messages,
                        tool_results,
                        steps,
                        total_tokens,
                    )

                return self._completed_result(
                    request,
                    messages,
                    tool_results,
                    steps,
                    total_tokens,
                )

            if (
                len(tool_results) + len(response.tool_calls)
                > request.max_tool_calls
            ):
                return self._failed_result(
                    request,
                    HarnessStopReason.TOOL_CALL_LIMIT_EXCEEDED,
                    messages,
                    tool_results,
                    steps,
                    total_tokens,
                )

            for call in response.tool_calls:
                if self._is_cancelled(request):
                    return self._cancelled_result(
                        request,
                        messages,
                        tool_results,
                        steps,
                        total_tokens,
                    )

                result = await self._tool_registry.execute(call)
                tool_results.append(result)
                messages.append(
                    ToolMessage(
                        tool_call_id=call.id,
                        content=self._tool_message_content(result),
                        status=result.status,
                    )
                )

        return self._failed_result(
            request,
            HarnessStopReason.MAX_STEPS_EXCEEDED,
            messages,
            tool_results,
            steps,
            total_tokens,
        )

    @staticmethod
    def _start_run(request: HarnessRunRequest) -> None:
        if request.agent_run.status is AgentRunStatus.CREATED:
            request.agent_run.transition_to(AgentRunStatus.RUNNING)

        if request.turn.status is TurnStatus.CREATED:
            request.turn.transition_to(TurnStatus.RUNNING)

    @staticmethod
    def _is_cancelled(request: HarnessRunRequest) -> bool:
        return (
            request.cancel_event is not None
            and request.cancel_event.is_set()
        )

    @staticmethod
    def _tool_message_content(result: ToolResult) -> dict[str, object]:
        return {
            "status": result.status.value,
            "output": result.output,
            "error": result.error,
            "artifacts": [
                {
                    "id": str(artifact.id),
                    "kind": artifact.kind,
                    "uri": artifact.uri,
                    "name": artifact.name,
                }
                for artifact in result.artifacts
            ],
        }

    @classmethod
    def _completed_result(
        cls,
        request: HarnessRunRequest,
        messages: list[Message],
        tool_results: list[ToolResult],
        steps: list[Step],
        total_tokens: int,
    ) -> HarnessRunResult:
        request.agent_run.transition_to(AgentRunStatus.SUCCEEDED)
        request.turn.transition_to(TurnStatus.SUCCEEDED)
        return cls._result(
            request,
            HarnessStopReason.COMPLETED,
            messages,
            tool_results,
            steps,
            total_tokens,
        )

    @classmethod
    def _failed_result(
        cls,
        request: HarnessRunRequest,
        reason: HarnessStopReason,
        messages: tuple[Message, ...] | list[Message],
        tool_results: list[ToolResult] | tuple[ToolResult, ...] = (),
        steps: list[Step] | tuple[Step, ...] = (),
        total_tokens: int = 0,
    ) -> HarnessRunResult:
        if request.agent_run.status is AgentRunStatus.RUNNING:
            request.agent_run.transition_to(AgentRunStatus.FAILED)
        if request.turn.status is TurnStatus.RUNNING:
            request.turn.transition_to(TurnStatus.FAILED)
        return cls._result(
            request,
            reason,
            messages,
            tool_results,
            steps,
            total_tokens,
        )

    @classmethod
    def _cancelled_result(
        cls,
        request: HarnessRunRequest,
        messages: list[Message],
        tool_results: list[ToolResult],
        steps: list[Step],
        total_tokens: int,
    ) -> HarnessRunResult:
        cls._cancel_run(request)
        return cls._result(
            request,
            HarnessStopReason.CANCELLED,
            messages,
            tool_results,
            steps,
            total_tokens,
        )

    @staticmethod
    def _cancel_run(request: HarnessRunRequest) -> None:
        if request.agent_run.status is AgentRunStatus.RUNNING:
            request.agent_run.transition_to(AgentRunStatus.CANCELLED)
        if request.turn.status is TurnStatus.RUNNING:
            request.turn.transition_to(TurnStatus.CANCELLED)

    @staticmethod
    def _result(
        request: HarnessRunRequest,
        reason: HarnessStopReason,
        messages: tuple[Message, ...] | list[Message],
        tool_results: tuple[ToolResult, ...] | list[ToolResult],
        steps: tuple[Step, ...] | list[Step],
        total_tokens: int,
    ) -> HarnessRunResult:
        return HarnessRunResult(
            run_status=request.agent_run.status,
            turn_status=request.turn.status,
            stop_reason=reason,
            messages=tuple(messages),
            tool_results=tuple(tool_results),
            steps=tuple(steps),
            total_tokens=total_tokens,
        )
