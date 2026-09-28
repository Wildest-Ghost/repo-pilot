"""Control Harness 的策略与生命周期协调边界。

在运行时契约冻结前，本包有意保持精简。策略、预算、审批、验证和任务
终结属于 Harness；模型提供方和进程执行则必须隐藏在独立端口之后。
"""

from repopilot.harness.loop import (
    HarnessLoop,
    HarnessRunRequest,
    HarnessRunResult,
    HarnessStopReason,
)

__all__ = [
    "HarnessLoop",
    "HarnessRunRequest",
    "HarnessRunResult",
    "HarnessStopReason",
]
