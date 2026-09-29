"""DeepSeek Chat Completions 的异步模型后端适配器。

本模块只处理 RepoPilot 内部模型契约与 DeepSeek HTTP 协议之间的转换：

* 将 ``SystemMessage``、``UserMessage``、``AssistantMessage`` 和
  ``ToolMessage`` 转换为 DeepSeek 的消息字典；
* 将 ``ToolDefinition`` 转换为函数工具定义；
* 将 DeepSeek 返回的文本、Tool Call 和 Token 使用量解析为 ``ModelResponse``；
* 把网络错误、超时和非法响应转换为稳定的适配器异常。

工具本身仍然由 RepoPilot 的 Harness 和 Tool Registry 执行。本适配器不会
读取工作区、调用 Shell，也不会决定某个 Tool Call 是否需要审批。
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from typing import cast
from uuid import UUID

import httpx

from repopilot.runtime.backend import ModelRequest, ModelResponse
from repopilot.runtime.messages import (
    AssistantMessage,
    Message,
    SystemMessage,
    UserMessage,
)
from repopilot.runtime.tool import ToolCall, ToolDefinition

_DEFAULT_BASE_URL = "https://api.deepseek.com"
_CHAT_COMPLETIONS_PATH = "/chat/completions"
_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_ERROR_BODY_LIMIT = 500


class DeepSeekBackendError(RuntimeError):
    """DeepSeek 适配器对外暴露的异常基类。"""


class DeepSeekConfigurationError(DeepSeekBackendError):
    """后端配置缺失或不符合要求。"""


class DeepSeekRequestError(DeepSeekBackendError):
    """请求尚未得到有效模型响应，例如网络请求失败。"""


class DeepSeekTimeoutError(DeepSeekRequestError):
    """模型请求超过 HTTP 超时限制。"""


class DeepSeekHTTPError(DeepSeekRequestError):
    """DeepSeek API 返回非成功 HTTP 状态码。"""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(
            f"DeepSeek API returned HTTP {status_code}: {body}"
        )


class DeepSeekResponseError(DeepSeekBackendError):
    """HTTP 请求成功但响应结构不符合预期。"""


class DeepSeekBackend:
    """通过 DeepSeek Chat Completions API 完成一次异步模型请求。

    默认情况下，实例会创建并复用一个 ``httpx.AsyncClient``。生产代码应
    在生命周期结束时调用 ``aclose``，或者使用 ``async with``。测试代码可以
    注入带有 ``MockTransport`` 的客户端，从而完全避免网络访问。

    M3.1 先固定使用非 Thinking 模式。等内部消息契约补充
    ``reasoning_content`` 后，再在 M4 开放 Thinking 模式。
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_seconds: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """创建后端，并从参数或 ``DEEPSEEK_API_KEY`` 读取 API Key。"""

        resolved_api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not resolved_api_key or not resolved_api_key.strip():
            raise DeepSeekConfigurationError(
                "DeepSeek API key is required. Set DEEPSEEK_API_KEY."
            )

        if not base_url.strip():
            raise DeepSeekConfigurationError("DeepSeek base_url must not be empty.")

        if timeout_seconds <= 0:
            raise DeepSeekConfigurationError(
                "DeepSeek timeout_seconds must be positive."
            )

        self._api_key = resolved_api_key
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None

    @property
    def backend_name(self) -> str:
        """返回稳定的模型后端名称。"""

        return "deepseek"

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """发送一次非流式请求，并返回 RepoPilot 的统一模型响应。"""

        payload = self._build_payload(request)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._client.post(
                f"{self._base_url}{_CHAT_COMPLETIONS_PATH}",
                headers=headers,
                json=payload,
            )
        except httpx.TimeoutException as error:
            raise DeepSeekTimeoutError(
                "DeepSeek request timed out."
            ) from error
        except httpx.RequestError as error:
            raise DeepSeekRequestError(
                f"DeepSeek request failed: {error}"
            ) from error

        if response.is_error:
            body = response.text[:_ERROR_BODY_LIMIT]
            raise DeepSeekHTTPError(response.status_code, body)

        try:
            data = response.json()
        except ValueError as error:
            raise DeepSeekResponseError(
                "DeepSeek response is not valid JSON."
            ) from error

        return self._parse_response(data)

    async def aclose(self) -> None:
        """关闭由当前后端自行创建的 HTTP 客户端。"""

        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> DeepSeekBackend:
        """支持 ``async with DeepSeekBackend(...)``。"""

        return self

    async def __aexit__(self, *_: object) -> None:
        """退出上下文时释放内部 HTTP 客户端。"""

        await self.aclose()

    @classmethod
    def _build_payload(cls, request: ModelRequest) -> dict[str, object]:
        """将内部请求转换为 DeepSeek Chat Completions 请求体。"""

        payload: dict[str, object] = {
            "model": request.model,
            "messages": [
                cls._serialize_message(message, request.messages)
                for message in request.messages
            ],
            # M3.1 关闭 Thinking，避免在 reasoning_content 契约完成前产生
            # 无法安全回传的提供方专属字段。
            "thinking": {"type": "disabled"},
        }

        if request.tools:
            payload["tools"] = [
                cls._serialize_tool(tool)
                for tool in request.tools
            ]
            payload["tool_choice"] = "auto"

        return payload

    @classmethod
    def _serialize_message(
        cls,
        message: Message,
        messages: tuple[Message, ...],
    ) -> dict[str, object]:
        """将单条内部消息转换为 DeepSeek 消息。"""

        if isinstance(message, SystemMessage):
            return {"role": "system", "content": message.content}

        if isinstance(message, UserMessage):
            return {"role": "user", "content": message.content}

        if isinstance(message, AssistantMessage):
            serialized: dict[str, object] = {
                "role": "assistant",
                "content": message.content,
            }
            if message.tool_calls:
                serialized["tool_calls"] = [
                    cls._serialize_tool_call(call)
                    for call in message.tool_calls
                ]
            return serialized

        provider_call_id = cls._find_provider_call_id(
            messages,
            message.tool_call_id,
        )
        return {
            "role": "tool",
            "tool_call_id": provider_call_id,
            "content": cls._serialize_content(message.content),
        }

    @staticmethod
    def _serialize_tool(tool: ToolDefinition) -> dict[str, object]:
        """将内部工具定义转换为 DeepSeek function tool 定义。"""

        if not _TOOL_NAME_PATTERN.fullmatch(tool.name):
            raise DeepSeekRequestError(
                "Tool name must contain only letters, numbers, '_' or '-'."
            )

        parameters: Mapping[str, object]
        if tool.parameters:
            parameters = tool.parameters
        else:
            parameters = {
                "type": "object",
                "properties": {},
            }

        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(parameters),
            },
        }

    @staticmethod
    def _serialize_tool_call(call: ToolCall) -> dict[str, object]:
        """将内部 ToolCall 转换为带提供方 ID 的 Assistant Tool Call。"""

        arguments = DeepSeekBackend._serialize_json(
            dict(call.arguments),
            f"arguments for tool '{call.name}'",
        )
        return {
            "id": call.provider_call_id or str(call.id),
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": arguments,
            },
        }

    @staticmethod
    def _serialize_content(content: object) -> str:
        """将结构化工具结果转成 API 要求的字符串内容。"""

        if isinstance(content, str):
            return content
        return DeepSeekBackend._serialize_json(content, "tool message content")

    @staticmethod
    def _serialize_json(value: object, field_name: str) -> str:
        """以稳定的 UTF-8 JSON 序列化请求字段。"""

        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as error:
            raise DeepSeekRequestError(
                f"Could not serialize {field_name} as JSON."
            ) from error

    @staticmethod
    def _find_provider_call_id(
        messages: tuple[Message, ...],
        tool_call_id: UUID,
    ) -> str:
        """根据内部 UUID 找回发给模型时使用的 Tool Call ID。"""

        for message in messages:
            if not isinstance(message, AssistantMessage):
                continue
            for call in message.tool_calls:
                if call.id == tool_call_id:
                    return call.provider_call_id or str(call.id)

        # 这通常只会在手工构造不完整历史时发生。使用 UUID 字符串仍然
        # 能保持请求可序列化，真实 DeepSeek 响应会提供 provider_call_id。
        return str(tool_call_id)

    @classmethod
    def _parse_response(cls, payload: object) -> ModelResponse:
        """解析 DeepSeek 响应，并拒绝不安全或不完整的结构。"""

        data = cls._require_mapping(payload, "response")
        if "error" in data:
            raise DeepSeekResponseError("DeepSeek response contains an error.")

        raw_choices = data.get("choices")
        if not isinstance(raw_choices, list) or not raw_choices:
            raise DeepSeekResponseError(
                "DeepSeek response must contain at least one choice."
            )
        choices = cast(list[object], raw_choices)

        choice = cls._require_mapping(choices[0], "response choice")
        message = cls._require_mapping(choice.get("message"), "response message")
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise DeepSeekResponseError(
                "DeepSeek message content must be a string or null."
            )

        raw_tool_calls_value = message.get("tool_calls", [])
        if raw_tool_calls_value is None:
            raw_tool_calls_value = []
        if not isinstance(raw_tool_calls_value, list):
            raise DeepSeekResponseError("DeepSeek tool_calls must be a list.")
        raw_tool_calls = cast(list[object], raw_tool_calls_value)

        tool_calls = tuple(
            cls._parse_tool_call(raw_call)
            for raw_call in raw_tool_calls
        )
        finish_reason = choice.get("finish_reason", "stop")
        if not isinstance(finish_reason, str):
            raise DeepSeekResponseError("DeepSeek finish_reason must be a string.")

        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=cls._parse_usage(data.get("usage", {})),
        )

    @classmethod
    def _parse_tool_call(cls, payload: object) -> ToolCall:
        """解析一个 DeepSeek function Tool Call。"""

        data = cls._require_mapping(payload, "tool call")
        provider_call_id = data.get("id")
        if provider_call_id is not None and not isinstance(provider_call_id, str):
            raise DeepSeekResponseError("Tool call id must be a string.")

        call_type = data.get("type", "function")
        if call_type != "function":
            raise DeepSeekResponseError(
                "Only function tool calls are supported in M3.1."
            )

        function = cls._require_mapping(data.get("function"), "tool function")
        name = function.get("name")
        if not isinstance(name, str) or not _TOOL_NAME_PATTERN.fullmatch(name):
            raise DeepSeekResponseError("Tool call function name is invalid.")

        raw_arguments = function.get("arguments", "{}")
        if not isinstance(raw_arguments, str):
            raise DeepSeekResponseError("Tool call arguments must be a JSON string.")

        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as error:
            raise DeepSeekResponseError(
                f"Tool call '{name}' contains invalid JSON arguments."
            ) from error

        if not isinstance(arguments, dict):
            raise DeepSeekResponseError(
                f"Tool call '{name}' arguments must be a JSON object."
            )

        return ToolCall(
            name=name,
            arguments=cast(Mapping[str, object], arguments),
            provider_call_id=provider_call_id,
        )

    @staticmethod
    def _parse_usage(payload: object) -> Mapping[str, int]:
        """提取 DeepSeek 响应中的整型 Token 使用量。"""

        if payload is None:
            return {}
        if not isinstance(payload, Mapping):
            raise DeepSeekResponseError("DeepSeek usage must be an object.")
        usage_payload = cast(Mapping[str, object], payload)

        usage: dict[str, int] = {}
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
        ):
            value = usage_payload.get(key)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise DeepSeekResponseError(
                    f"DeepSeek usage field '{key}' must be an integer."
                )
            usage[key] = value
        return usage

    @staticmethod
    def _require_mapping(
        value: object,
        field_name: str,
    ) -> Mapping[str, object]:
        """把不受信任的 JSON 值收窄为对象映射。"""

        if not isinstance(value, Mapping):
            raise DeepSeekResponseError(
                f"DeepSeek {field_name} must be an object."
            )
        return cast(Mapping[str, object], value)
