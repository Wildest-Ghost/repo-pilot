"""Session、Turn 和 Step 的运行时契约。

三者的关系是：

* Session 表示一次 AgentRun 的运行时会话；
* Turn 表示一次开始、恢复或审批后的操作；
* Step 表示一次模型请求。

本模块只描述运行时状态，不负责调用模型或执行工具。
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID, uuid4


def _new_uuid_list() -> list[UUID]:
    """创建独立的 UUID 列表，避免默认值类型不明确或被共享。"""

    return []


class TurnKind(StrEnum):
    """触发一个 Turn 的操作类型。"""

    USER_REQUEST = "user_request"
    APPROVAL_RESUME = "approval_resume"
    SYSTEM_RESUME = "system_resume"


class TurnStatus(StrEnum):
    """Turn 的生命周期状态。"""

    CREATED = "created"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    """单次模型请求的状态。"""

    CREATED = "created"
    COMPLETED = "completed"
    FAILED = "failed"


class InvalidTurnTransitionError(ValueError):
    """Turn 尝试执行非法状态迁移时抛出。"""


class InvalidStepTransitionError(ValueError):
    """Step 尝试执行非法状态迁移时抛出。"""


@dataclass
class Session:
    """保存一个 AgentRun 的会话身份和 Turn 顺序。"""

    agent_run_id: UUID
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _turn_ids: list[UUID] = field(
        default_factory=_new_uuid_list,
        repr=False,
    )

    @property
    def turn_ids(self) -> tuple[UUID, ...]:
        """返回 Turn ID 的只读有序视图。"""

        return tuple(self._turn_ids)

    def append_turn(self, turn_id: UUID) -> None:
        """向会话追加一个 Turn，并拒绝重复追加。"""

        if turn_id in self._turn_ids:
            raise ValueError(f"Turn '{turn_id}' is already attached to Session.")

        self._turn_ids.append(turn_id)
        self.updated_at = datetime.now(UTC)


@dataclass
class Turn:
    """表示一次用户请求、审批恢复或系统恢复操作。"""

    session_id: UUID
    kind: TurnKind
    id: UUID = field(default_factory=uuid4)
    status: TurnStatus = TurnStatus.CREATED
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    _step_ids: list[UUID] = field(
        default_factory=_new_uuid_list,
        repr=False,
    )

    _ALLOWED_TRANSITIONS: ClassVar[
        dict[TurnStatus, frozenset[TurnStatus]]
    ] = {
        TurnStatus.CREATED: frozenset({TurnStatus.RUNNING}),
        TurnStatus.RUNNING: frozenset(
            {
                TurnStatus.WAITING_APPROVAL,
                TurnStatus.SUCCEEDED,
                TurnStatus.FAILED,
                TurnStatus.CANCELLED,
            }
        ),
        TurnStatus.WAITING_APPROVAL: frozenset(
            {
                TurnStatus.RUNNING,
                TurnStatus.CANCELLED,
            }
        ),
        TurnStatus.SUCCEEDED: frozenset(),
        TurnStatus.FAILED: frozenset(),
        TurnStatus.CANCELLED: frozenset(),
    }

    _TERMINAL_STATUSES: ClassVar[frozenset[TurnStatus]] = frozenset(
        {
            TurnStatus.SUCCEEDED,
            TurnStatus.FAILED,
            TurnStatus.CANCELLED,
        }
    )

    @property
    def step_ids(self) -> tuple[UUID, ...]:
        """返回当前 Turn 内 Step ID 的只读有序视图。"""

        return tuple(self._step_ids)

    def append_step(self, step_id: UUID) -> None:
        """追加一个 Step，并拒绝重复追加。"""

        if step_id in self._step_ids:
            raise ValueError(f"Step '{step_id}' is already attached to Turn.")

        self._step_ids.append(step_id)
        self.updated_at = datetime.now(UTC)

    def transition_to(self, target_status: TurnStatus) -> None:
        """执行 Turn 状态迁移，并在终态记录完成时间。"""

        allowed_statuses = self._ALLOWED_TRANSITIONS[self.status]

        if target_status not in allowed_statuses:
            raise InvalidTurnTransitionError(
                f"Cannot transition Turn from '{self.status.value}' "
                f"to '{target_status.value}'."
            )

        now = datetime.now(UTC)
        self.status = target_status
        self.updated_at = now

        if target_status in self._TERMINAL_STATUSES:
            self.finished_at = now


@dataclass
class Step:
    """表示一次模型请求及其在当前 Turn 中的顺序。"""

    turn_id: UUID
    sequence: int
    id: UUID = field(default_factory=uuid4)
    status: StepStatus = StepStatus.CREATED
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    _ALLOWED_TRANSITIONS: ClassVar[
        dict[StepStatus, frozenset[StepStatus]]
    ] = {
        StepStatus.CREATED: frozenset(
            {
                StepStatus.COMPLETED,
                StepStatus.FAILED,
            }
        ),
        StepStatus.COMPLETED: frozenset(),
        StepStatus.FAILED: frozenset(),
    }

    def transition_to(self, target_status: StepStatus) -> None:
        """完成或标记一次模型请求，并记录完成时间。"""

        allowed_statuses = self._ALLOWED_TRANSITIONS[self.status]

        if target_status not in allowed_statuses:
            raise InvalidStepTransitionError(
                f"Cannot transition Step from '{self.status.value}' "
                f"to '{target_status.value}'."
            )

        self.status = target_status

        if target_status in {
            StepStatus.COMPLETED,
            StepStatus.FAILED,
        }:
            self.completed_at = datetime.now(UTC)
