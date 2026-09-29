"""DeepSeekBackend 的协议转换和错误边界测试。"""

import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

from repopilot.adapters import (
    DeepSeekBackend,
    DeepSeekConfigurationError,
    DeepSeekHTTPError,
    DeepSeekResponseError,
    DeepSeekTimeoutError,
)
from repopilot.harness import HarnessLoop, HarnessRunRequest, HarnessStopReason
from repopilot.runtime import (
    AgentRun,
    AssistantMessage,
    Message,
    ModelRequest,
    Session,
    SystemMessage,
    ToolCall,
    ToolDefinition,
    ToolMessage,
    ToolResultStatus,
    Turn,
    TurnKind,
    UserMessage,
)
from repopilot.tools import build_read_only_registry


def make_request(*messages: Message) -> ModelRequest:
    """构造协议转换测试使用的模型请求。"""

    return ModelRequest(
        model="deepseek-flash",
        session_id=uuid4(),
        turn_id=uuid4(),
        step_id=uuid4(),
        messages=messages,
        tools=(
            ToolDefinition(
                name="read_file",
                description="读取一个文本文件。",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
        ),
    )


async def test_complete_serializes_internal_messages_and_tools() -> None:
    """内部消息、Tool Call 和工具定义应转换为 DeepSeek 请求格式。"""

    internal_call_id = uuid4()
    provider_call_id = "call_read_1"
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "文件已经读取。",
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 5,
                    "total_tokens": 16,
                },
            },
        )

    assistant = AssistantMessage(
        content=None,
        tool_calls=(
            ToolCall(
                id=internal_call_id,
                provider_call_id=provider_call_id,
                name="read_file",
                arguments={"path": "README.md"},
            ),
        ),
    )
    request = make_request(
        SystemMessage(content="You are a repository assistant."),
        UserMessage(content="读取 README.md"),
        assistant,
        ToolMessage(
            tool_call_id=internal_call_id,
            content={"status": "completed", "output": "hello"},
            status=ToolResultStatus.COMPLETED,
        ),
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = DeepSeekBackend(
            api_key="test-key",
            base_url="https://example.test",
            client=client,
        )
        response = await backend.complete(request)

    payload = captured["payload"]
    assert captured["url"] == "https://example.test/chat/completions"
    assert captured["authorization"] == "Bearer test-key"
    assert isinstance(payload, dict)
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["tool_choice"] == "auto"
    assert payload["messages"][-1]["tool_call_id"] == provider_call_id
    assert payload["tools"][0]["function"]["name"] == "read_file"
    assert response.content == "文件已经读取。"
    assert response.usage["total_tokens"] == 16


async def test_complete_parses_tool_call_and_keeps_provider_call_id() -> None:
    """DeepSeek Tool Call 应生成内部 UUID，同时保留提供方调用 ID。"""

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_123",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path":"README.md"}',
                                    },
                                }
                            ],
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = DeepSeekBackend(api_key="test-key", client=client)
        response = await backend.complete(make_request(UserMessage(content="读取文件")))

    call = response.tool_calls[0]
    assert call.provider_call_id == "call_123"
    assert isinstance(call.id, UUID)
    assert str(call.id) != "call_123"
    assert call.name == "read_file"
    assert call.arguments == {"path": "README.md"}


async def test_complete_rejects_invalid_tool_arguments() -> None:
    """非法 JSON 参数必须在适配器边界被拒绝。"""

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_bad",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": "not-json",
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = DeepSeekBackend(api_key="test-key", client=client)
        with pytest.raises(DeepSeekResponseError, match="invalid JSON"):
            await backend.complete(make_request(UserMessage(content="读取文件")))


async def test_complete_maps_http_error_without_exposing_configuration() -> None:
    """非 2xx 响应应转换为带状态码的请求异常。"""

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid api key")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = DeepSeekBackend(api_key="secret-key", client=client)
        with pytest.raises(DeepSeekHTTPError) as error_info:
            await backend.complete(make_request(UserMessage(content="hello")))

    assert error_info.value.status_code == 401
    assert "secret-key" not in str(error_info.value)


async def test_complete_maps_timeout() -> None:
    """网络超时应转换为稳定的 DeepSeekTimeoutError。"""

    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = DeepSeekBackend(api_key="test-key", client=client)
        with pytest.raises(DeepSeekTimeoutError):
            await backend.complete(make_request(UserMessage(content="hello")))


async def test_complete_preserves_cancellation() -> None:
    """取消模型请求时，适配器必须让 CancelledError 继续向上传播。"""

    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(_: httpx.Request) -> httpx.Response:
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = DeepSeekBackend(api_key="test-key", client=client)
        task = asyncio.create_task(
            backend.complete(make_request(UserMessage(content="hello")))
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_backend_requires_api_key() -> None:
    """没有显式参数或环境变量时，后端不应被创建。"""

    with pytest.raises(DeepSeekConfigurationError, match="API key"):
        DeepSeekBackend(api_key="")


async def test_deepseek_backend_completes_read_only_harness_loop(
    tmp_path: Path,
) -> None:
    """DeepSeek 适配器应能驱动现有只读工具循环完成两次模型请求。"""

    (tmp_path / "README.md").write_text("RepoPilot test file", encoding="utf-8")
    captured_payloads: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured_payloads.append(payload)

        if len(captured_payloads) == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_read_1",
                                        "type": "function",
                                        "function": {
                                            "name": "read_file",
                                            "arguments": '{"path":"README.md"}',
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                    "usage": {"total_tokens": 7},
                },
            )

        assert payload["messages"][-1]["tool_call_id"] == "call_read_1"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "README.md 已检查。",
                        },
                    }
                ],
                "usage": {"total_tokens": 5},
            },
        )

    run = AgentRun(task_id=uuid4(), backend="deepseek", model="deepseek-flash")
    session = Session(agent_run_id=run.id)
    turn = Turn(session_id=session.id, kind=TurnKind.USER_REQUEST)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = DeepSeekBackend(
            api_key="test-key",
            base_url="https://example.test",
            client=client,
        )
        result = await HarnessLoop(
            backend=backend,
            tool_registry=build_read_only_registry(tmp_path),
        ).run(
            HarnessRunRequest(
                agent_run=run,
                session=session,
                turn=turn,
                model="deepseek-flash",
                messages=(UserMessage(content="检查 README.md"),),
            )
        )

    assert result.stop_reason is HarnessStopReason.COMPLETED
    assert result.messages[-1].content == "README.md 已检查。"
    assert len(result.tool_results) == 1
    assert len(captured_payloads) == 2
