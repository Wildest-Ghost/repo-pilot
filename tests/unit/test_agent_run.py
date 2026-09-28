"""AgentRun 领域模型的状态和不变量测试。"""

from uuid import uuid4

import pytest

from repopilot.runtime import (
    AgentRun,
    AgentRunStatus,
    InvalidAgentRunTransitionError,
)


def test_agent_run_can_resume_after_approval() -> None:
    """运行可以暂停等待审批，审批后回到运行状态并最终成功。"""

    run = AgentRun(
        task_id=uuid4(),
        backend="deepseek",
        model="deepseek-chat",
    )

    run.transition_to(AgentRunStatus.RUNNING)
    run.transition_to(AgentRunStatus.WAITING_APPROVAL)
    run.transition_to(AgentRunStatus.RUNNING)
    run.transition_to(AgentRunStatus.SUCCEEDED)

    assert run.status is AgentRunStatus.SUCCEEDED
    assert run.is_terminal
    assert run.finished_at is not None
    assert run.updated_at == run.finished_at


def test_agent_run_rejects_invalid_transition() -> None:
    """不能从 CREATED 直接跳到成功，必须经过运行状态。"""

    run = AgentRun(
        task_id=uuid4(),
        backend="deepseek",
        model="deepseek-chat",
    )

    with pytest.raises(InvalidAgentRunTransitionError):
        run.transition_to(AgentRunStatus.SUCCEEDED)


def test_terminal_agent_run_cannot_transition_again() -> None:
    """成功后的 AgentRun 是终态，不能再次恢复或修改状态。"""

    run = AgentRun(
        task_id=uuid4(),
        backend="deepseek",
        model="deepseek-chat",
    )
    run.transition_to(AgentRunStatus.RUNNING)
    run.transition_to(AgentRunStatus.SUCCEEDED)

    with pytest.raises(InvalidAgentRunTransitionError):
        run.transition_to(AgentRunStatus.RUNNING)


@pytest.mark.parametrize(
    ("backend", "model"),
    [
        ("", "deepseek-chat"),
        ("deepseek", ""),
    ],
)
def test_agent_run_requires_backend_and_model(
    backend: str,
    model: str,
) -> None:
    """运行记录必须带有可审计的后端和模型标识。"""

    with pytest.raises(ValueError):
        AgentRun(
            task_id=uuid4(),
            backend=backend,
            model=model,
        )
