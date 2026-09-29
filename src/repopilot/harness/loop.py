"""异步 HarnessLoop。

M2 的循环只支持只读工具。它负责：

* 向 AgentBackend 发起模型请求；
* 识别模型是否返回 ToolCall；
* 通过 ToolOrchestrator 执行已注册工具；
* 将 ToolResult 作为内部 ToolMessage 放回上下文；
* 应用步骤、工具调用、Token、超时和取消限制。

Docker 沙箱由独立 ExecutionGateway 提供；本模块只负责调用它暴露的工具，
不直接创建宿主机进程。运行事件通过可选 EventSink 记录，便于审计和后续 SSE
投影，但 M3 仍然只承诺内存事件存储。
"""

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from repopilot.harness.approval import ApprovalRequest
from repopilot.harness.orchestrator import ToolOrchestrator
from repopilot.runtime.backend import AgentBackend, ModelRequest
from repopilot.runtime.events import EventSink, RuntimeEvent, RuntimeEventType
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
    WAITING_APPROVAL = "waiting_approval"
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
    approval_id: UUID | None = None
    prior_tool_results: tuple[ToolResult, ...] = ()

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
    approval_request: ApprovalRequest | None = None


class HarnessLoop:
    """在模型和受治理工具之间驱动一次异步执行循环。"""

    def __init__(
        self,
        backend: AgentBackend,
        tool_registry: ToolRegistry,
        *,
        tool_orchestrator: ToolOrchestrator | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self._backend = backend
        self._tool_orchestrator = tool_orchestrator or ToolOrchestrator(
            tool_registry
        )
        self._event_sink = event_sink

    async def run(self, request: HarnessRunRequest) -> HarnessRunResult:
        """执行一次受步骤、Token、时间和取消约束的 Agent Run。"""

        self._start_run(request)
        self._emit_start_events(request)

        try:
            if request.timeout_seconds is None:
                result = await self._run_without_timeout(request)
            else:
                async with asyncio.timeout(request.timeout_seconds):
                    result = await self._run_without_timeout(request)
            self._emit_final_status(request, result)
            return result
        except TimeoutError:
            result = self._failed_result(
                request,
                HarnessStopReason.TIMEOUT,
                messages=request.messages,
            )
            self._emit_final_status(request, result)
            return result
        except asyncio.CancelledError:
            self._cancel_run(request)
            self._emit_status_event(request, reason=HarnessStopReason.CANCELLED)
            raise
        except Exception:
            result = self._failed_result(
                request,
                HarnessStopReason.MODEL_ERROR,
                messages=request.messages,
            )
            self._emit_final_status(request, result)
            return result

    async def _run_without_timeout(
        self,
        request: HarnessRunRequest,
    ) -> HarnessRunResult:
        messages = list(request.messages)
        tool_results: list[ToolResult] = list(request.prior_tool_results)
        steps: list[Step] = []
        total_tokens = 0

        if request.turn.id not in request.session.turn_ids:
            request.session.append_turn(request.turn.id)

        if request.approval_id is not None:
            outcome = await self._tool_orchestrator.resume_approved(
                request.agent_run.id,
                request.approval_id,
            )
            if outcome.approval_request is not None:
                return self._waiting_approval_result(
                    request,
                    messages,
                    tool_results,
                    steps,
                    total_tokens,
                    outcome.approval_request,
                )

            tool_results.append(outcome.result)
            self._emit_event(
                request,
                RuntimeEventType.APPROVAL_RESOLVED,
                request.approval_id,
                {
                    "status": outcome.result.status.value,
                    "tool_call_id": str(outcome.result.tool_call_id),
                },
            )
            self._emit_tool_result_event(request, outcome.result)
            messages.append(
                ToolMessage(
                    tool_call_id=outcome.result.tool_call_id,
                    content=self._tool_message_content(outcome.result),
                    status=outcome.result.status,
                )
            )

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
            self._emit_event(
                request,
                RuntimeEventType.STEP_CREATED,
                step.id,
                {"sequence": sequence, "turn_id": str(request.turn.id)},
            )

            model_request = ModelRequest(
                model=request.model,
                session_id=request.session.id,
                turn_id=request.turn.id,
                step_id=step.id,
                messages=tuple(messages),
                tools=self._tool_orchestrator.definitions(),
            )
            self._emit_event(
                request,
                RuntimeEventType.MODEL_REQUESTED,
                step.id,
                {
                    "model": request.model,
                    "message_count": len(messages),
                    "tool_names": [
                        definition.name
                        for definition in model_request.tools
                    ],
                },
            )
            response = await self._backend.complete(model_request)
            self._emit_event(
                request,
                RuntimeEventType.MODEL_RESPONDED,
                step.id,
                {
                    "finish_reason": response.finish_reason,
                    "content": self._bounded_text(response.content),
                    "tool_call_count": len(response.tool_calls),
                    "usage": dict(response.usage),
                },
            )
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

                self._emit_event(
                    request,
                    RuntimeEventType.TOOL_CALL_REQUESTED,
                    call.id,
                    {
                        "name": call.name,
                        "provider_call_id": call.provider_call_id,
                        "arguments": self._bounded_text(call.arguments),
                    },
                )
                outcome = await self._tool_orchestrator.execute(
                    request.agent_run.id,
                    call,
                )
                result = outcome.result
                tool_results.append(result)
                self._emit_tool_result_event(request, result)

                if outcome.approval_request is not None:
                    self._emit_event(
                        request,
                        RuntimeEventType.APPROVAL_REQUESTED,
                        outcome.approval_request.id,
                        {
                            "tool_call_id": str(call.id),
                            "tool_name": call.name,
                            "reason": outcome.approval_request.reason,
                        },
                    )
                    return self._waiting_approval_result(
                        request,
                        messages,
                        tool_results,
                        steps,
                        total_tokens,
                        outcome.approval_request,
                    )

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

    def _emit_start_events(self, request: HarnessRunRequest) -> None:
        """记录一次运行的会话、Turn 和初始状态事实。"""

        self._emit_once(
            request,
            RuntimeEventType.SESSION_CREATED,
            request.session.id,
            {
                "agent_run_id": str(request.agent_run.id),
                "workspace_root": request.agent_run.workspace_root,
            },
        )
        self._emit_once(
            request,
            RuntimeEventType.TURN_CREATED,
            request.turn.id,
            {"kind": request.turn.kind.value},
        )
        self._emit_status_event(request, reason=None)

    def _emit_final_status(
        self,
        request: HarnessRunRequest,
        result: HarnessRunResult,
    ) -> None:
        """记录停止原因和最终状态，但不把完整上下文写入事件。"""

        self._emit_event(
            request,
            RuntimeEventType.STATUS_CHANGED,
            request.agent_run.id,
            {
                "run_status": result.run_status.value,
                "turn_status": result.turn_status.value,
                "stop_reason": result.stop_reason.value,
                "total_tokens": result.total_tokens,
                "step_count": len(result.steps),
                "tool_result_count": len(result.tool_results),
            },
        )

    def _emit_status_event(
        self,
        request: HarnessRunRequest,
        *,
        reason: HarnessStopReason | None,
    ) -> None:
        """记录当前运行状态，供取消和异常路径使用。"""

        payload: dict[str, object] = {
            "run_status": request.agent_run.status.value,
            "turn_status": request.turn.status.value,
        }
        if reason is not None:
            payload["stop_reason"] = reason.value
        self._emit_event(
            request,
            RuntimeEventType.STATUS_CHANGED,
            request.agent_run.id,
            payload,
        )

    def _emit_tool_result_event(
        self,
        request: HarnessRunRequest,
        result: ToolResult,
    ) -> None:
        """记录工具状态和有界摘要，避免把无限输出塞入事件或 Prompt。"""

        self._emit_event(
            request,
            RuntimeEventType.TOOL_RESULT_RECORDED,
            result.tool_call_id,
            {
                "status": result.status.value,
                "error": result.error,
                "output": self._bounded_text(result.output),
                "artifact_ids": [str(artifact.id) for artifact in result.artifacts],
            },
        )

    def _emit_once(
        self,
        request: HarnessRunRequest,
        event_type: RuntimeEventType,
        subject_id: UUID,
        payload: dict[str, object],
    ) -> None:
        """恢复审批时避免重复创建同一会话或 Turn 事件。"""

        if self._event_sink is None:
            return
        if any(
            event.event_type is event_type and event.subject_id == subject_id
            for event in self._event_sink.get_events(request.agent_run.id)
        ):
            return
        self._emit_event(request, event_type, subject_id, payload)

    def _emit_event(
        self,
        request: HarnessRunRequest,
        event_type: RuntimeEventType,
        subject_id: UUID,
        payload: dict[str, object],
    ) -> None:
        """向 EventSink 追加一条有序事件。

        M3 的内存 EventStore 通过已有事件数分配序号；M4 接入并发持久化
        存储后，序号分配必须下沉到事务或事件存储本身。
        """

        if self._event_sink is None:
            return
        events = self._event_sink.get_events(request.agent_run.id)
        self._event_sink.append(
            RuntimeEvent(
                agent_run_id=request.agent_run.id,
                event_type=event_type,
                subject_id=subject_id,
                sequence=len(events) + 1,
                payload=payload,
            )
        )

    @staticmethod
    def _bounded_text(value: object, limit: int = 4096) -> str | None:
        """将任意工具输出转换为有限文本摘要。"""

        if value is None:
            return None
        text = str(value)
        return text if len(text) <= limit else f"{text[:limit]}...<truncated>"

    @staticmethod
    def _start_run(request: HarnessRunRequest) -> None:
        if request.agent_run.status in {
            AgentRunStatus.CREATED,
            AgentRunStatus.WAITING_APPROVAL,
        }:
            request.agent_run.transition_to(AgentRunStatus.RUNNING)

        if request.turn.status in {
            TurnStatus.CREATED,
            TurnStatus.WAITING_APPROVAL,
        }:
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
    def _waiting_approval_result(
        cls,
        request: HarnessRunRequest,
        messages: list[Message],
        tool_results: list[ToolResult],
        steps: list[Step],
        total_tokens: int,
        approval_request: ApprovalRequest,
    ) -> HarnessRunResult:
        """将审批等待作为可恢复状态返回，不把它伪装成工具失败。"""

        if request.agent_run.status is AgentRunStatus.RUNNING:
            request.agent_run.transition_to(AgentRunStatus.WAITING_APPROVAL)
        if request.turn.status is TurnStatus.RUNNING:
            request.turn.transition_to(TurnStatus.WAITING_APPROVAL)
        return cls._result(
            request,
            HarnessStopReason.WAITING_APPROVAL,
            messages,
            tool_results,
            steps,
            total_tokens,
            approval_request,
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
        approval_request: ApprovalRequest | None = None,
    ) -> HarnessRunResult:
        return HarnessRunResult(
            run_status=request.agent_run.status,
            turn_status=request.turn.status,
            stop_reason=reason,
            messages=tuple(messages),
            tool_results=tuple(tool_results),
            steps=tuple(steps),
            total_tokens=total_tokens,
            approval_request=approval_request,
        )
