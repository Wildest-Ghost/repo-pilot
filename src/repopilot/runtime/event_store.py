"""进程内运行时事件存储。

该实现用于 M1 的契约测试和 FakeBackend 场景。它不提供跨进程持久化，
但会校验事件序号连续，提前暴露调用方乱序写入的问题。
"""

from dataclasses import dataclass, field
from uuid import UUID

from repopilot.runtime.events import EventSink, RuntimeEvent


def _new_event_map() -> dict[UUID, list[RuntimeEvent]]:
    """为每个仓库实例创建独立的可变事件字典。"""

    return {}


@dataclass
class InMemoryEventStore(EventSink):
    """按 AgentRun 保存有序运行时事件。"""

    _events: dict[UUID, list[RuntimeEvent]] = field(
        default_factory=_new_event_map
    )

    def append(self, event: RuntimeEvent) -> None:
        """追加事件，并拒绝不连续的 sequence。"""

        events = self._events.setdefault(event.agent_run_id, [])
        expected_sequence = len(events) + 1

        if event.sequence != expected_sequence:
            raise ValueError(
                f"Expected event sequence {expected_sequence}, "
                f"received {event.sequence}."
            )

        events.append(event)

    def get_events(self, agent_run_id: UUID) -> tuple[RuntimeEvent, ...]:
        """返回事件的只读有序视图。"""

        return tuple(self._events.get(agent_run_id, ()))
