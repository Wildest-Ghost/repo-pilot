"""M2 只读工作区工具的安全边界测试。"""

from pathlib import Path
from typing import cast

from repopilot.runtime import ToolCall, ToolResultStatus
from repopilot.tools import build_read_only_registry


async def test_readonly_registry_lists_reads_and_searches(tmp_path: Path) -> None:
    """三项只读工具应能访问工作区内的文本内容。"""

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "example.py").write_text(
        "answer = 42\n",
        encoding="utf-8",
    )
    registry = build_read_only_registry(tmp_path)

    listed = await registry.execute(
        ToolCall(name="list_files", arguments={"path": "src"})
    )
    read = await registry.execute(
        ToolCall(name="read_file", arguments={"path": "src/example.py"})
    )
    searched = await registry.execute(
        ToolCall(
            name="search_text",
            arguments={"query": "answer", "path": "src"},
        )
    )

    assert listed.status is ToolResultStatus.COMPLETED
    assert read.status is ToolResultStatus.COMPLETED
    assert searched.status is ToolResultStatus.COMPLETED
    read_output = cast(dict[str, object], read.output)
    search_output = cast(dict[str, object], searched.output)
    matches = cast(list[dict[str, object]], search_output["matches"])
    assert read_output["content"] == "answer = 42\n"
    assert matches[0]["line"] == 1


async def test_readonly_registry_rejects_workspace_escape(tmp_path: Path) -> None:
    """路径逃逸不能访问工作区外的文件。"""

    registry = build_read_only_registry(tmp_path)

    result = await registry.execute(
        ToolCall(name="read_file", arguments={"path": "../outside.txt"})
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error is not None
    assert "workspace" in result.error


async def test_readonly_registry_rejects_unknown_tool(tmp_path: Path) -> None:
    """未注册的工具必须被拒绝，而不是尝试动态执行。"""

    registry = build_read_only_registry(tmp_path)

    result = await registry.execute(ToolCall(name="run_command"))

    assert result.status is ToolResultStatus.REJECTED
