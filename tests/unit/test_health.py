"""HTTP 健康检查的最小契约测试。"""

from typing import Any

from apps.api.main import app
from fastapi.testclient import TestClient


def test_health_check() -> None:
    """健康检查应返回稳定的 200 响应和状态标识。"""

    client: Any = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
