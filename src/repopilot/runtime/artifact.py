"""运行产物契约。

Artifact 只保存产物的可审计元数据和引用，不把大文件内容直接塞进
运行事件或模型上下文。实际文件由未来的 Artifact Store 管理。
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True)
class Artifact:
    """表示一次工具执行或验证产生的外部产物。"""

    kind: str
    uri: str
    id: UUID = field(default_factory=uuid4)
    name: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
