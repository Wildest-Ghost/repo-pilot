"""AgentRun（智能体运行）领域模型。

一个 Task 描述用户希望完成的目标，而一个 AgentRun 表示系统针对
该 Task 发起的一次执行尝试。一次 Task 可以拥有多次 AgentRun，
例如第一次运行失败后重新运行，或审批恢复后继续运行。

本模块只负责运行身份、状态和状态迁移规则，不调用模型、不执行工具，
也不直接访问数据库。
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID, uuid4


class AgentRunStatus(StrEnum):
    """AgentRun 在最小生命周期中的状态集合。"""

    CREATED = "created"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvalidAgentRunTransitionError(ValueError):
    """AgentRun 尝试执行非法状态迁移时抛出。"""


@dataclass
class AgentRun:
    """表示针对一个 Task 的一次智能体执行尝试。

    `backend` 和 `model` 只记录本次运行选用的模型后端与模型标识，
    不负责真正调用它们。将这些信息保存到运行对象，可以保证后续恢复
    或审计时知道这次运行使用过什么配置。
    """

    task_id: UUID
    backend: str
    model: str
    workspace_root: str | None = None
    id: UUID = field(default_factory=uuid4)
    status: AgentRunStatus = AgentRunStatus.CREATED
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    _ALLOWED_TRANSITIONS: ClassVar[
        dict[AgentRunStatus, frozenset[AgentRunStatus]]
    ] = {
        AgentRunStatus.CREATED: frozenset({AgentRunStatus.RUNNING}),
        AgentRunStatus.RUNNING: frozenset(
            {
                AgentRunStatus.WAITING_APPROVAL,
                AgentRunStatus.SUCCEEDED,
                AgentRunStatus.FAILED,
                AgentRunStatus.CANCELLED,
            }
        ),
        AgentRunStatus.WAITING_APPROVAL: frozenset(
            {
                AgentRunStatus.RUNNING,
                AgentRunStatus.CANCELLED,
            }
        ),
        AgentRunStatus.SUCCEEDED: frozenset(),
        AgentRunStatus.FAILED: frozenset(),
        AgentRunStatus.CANCELLED: frozenset(),
    }

    _TERMINAL_STATUSES: ClassVar[frozenset[AgentRunStatus]] = frozenset(
        {
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }
    )

    def __post_init__(self) -> None:
        """校验模型后端标识，避免创建出无法审计的运行记录。"""

        self.backend = self.backend.strip()
        self.model = self.model.strip()

        if not self.backend:
            raise ValueError("AgentRun backend must not be empty.")

        if not self.model:
            raise ValueError("AgentRun model must not be empty.")

        if self.workspace_root is not None:
            self.workspace_root = self.workspace_root.strip()
            if not self.workspace_root:
                raise ValueError("AgentRun workspace_root must not be empty.")

    @property
    def is_terminal(self) -> bool:
        """返回运行是否已经进入不可继续迁移的终态。"""

        return self.status in self._TERMINAL_STATUSES

    def transition_to(self, target_status: AgentRunStatus) -> None:
        """执行一次受约束的状态迁移，并刷新运行时间。

        终态会额外记录 `finished_at`。状态迁移表集中放在领域对象中，
        这样 API、Harness 和未来的后台任务不会各自复制一套规则。
        """

        allowed_statuses = self._ALLOWED_TRANSITIONS[self.status]

        if target_status not in allowed_statuses:
            raise InvalidAgentRunTransitionError(
                f"Cannot transition AgentRun from '{self.status.value}' "
                f"to '{target_status.value}'."
            )

        now = datetime.now(UTC)
        self.status = target_status
        self.updated_at = now

        if target_status in self._TERMINAL_STATUSES:
            self.finished_at = now
