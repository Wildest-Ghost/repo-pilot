"""用于单元测试的确定性模型后端。"""

from dataclasses import dataclass, field
from typing import ClassVar

from repopilot.runtime.backend import (
    AgentBackend,
    ModelRequest,
    ModelResponse,
)


def _new_responses() -> list[ModelResponse]:
    """创建预设模型响应列表。"""

    return []


def _new_requests() -> list[ModelRequest]:
    """创建模型请求记录列表。"""

    return []


@dataclass
class FakeBackend(AgentBackend):
    """按预先提供的响应顺序返回结果，不访问网络。"""

    responses: list[ModelResponse] = field(default_factory=_new_responses)
    requests: list[ModelRequest] = field(default_factory=_new_requests)

    _BACKEND_NAME: ClassVar[str] = "fake"

    @property
    def backend_name(self) -> str:
        """返回 FakeBackend 的稳定标识。"""

        return self._BACKEND_NAME

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """记录请求并返回下一条预设响应。"""

        self.requests.append(request)

        if not self.responses:
            raise RuntimeError("FakeBackend has no response left.")

        return self.responses.pop(0)
