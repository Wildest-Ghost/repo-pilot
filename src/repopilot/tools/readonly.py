"""M2 第一批只读工作区工具。

这些工具只读取工作区内容，不修改文件、不启动 Shell，也不访问网络。
文件系统操作放到 asyncio.to_thread 中，避免阻塞异步 HarnessLoop。
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from repopilot.runtime.tool import ToolDefinition
from repopilot.tools.registry import ToolRegistry


@dataclass(frozen=True)
class ReadOnlyWorkspaceTools:
    """在限定根目录内提供安全的只读文件操作。"""

    root: Path

    def __post_init__(self) -> None:
        """固定工作区绝对路径，后续所有路径都必须位于其中。"""

        object.__setattr__(self, "root", self.root.resolve())

    async def list_files(self, arguments: Mapping[str, object]) -> object:
        """列出目录下的文件和子目录。"""

        return await asyncio.to_thread(self._list_files_sync, arguments)

    async def read_file(self, arguments: Mapping[str, object]) -> object:
        """读取一个 UTF-8 文本文件，并限制最大字符数。"""

        return await asyncio.to_thread(self._read_file_sync, arguments)

    async def search_text(self, arguments: Mapping[str, object]) -> object:
        """在工作区内搜索文本，并返回有限数量的匹配行。"""

        return await asyncio.to_thread(self._search_text_sync, arguments)

    def _list_files_sync(self, arguments: Mapping[str, object]) -> object:
        path = self._resolve_path(arguments.get("path", "."))
        if not path.is_dir():
            raise ValueError(f"Not a directory: {self._relative_path(path)}")

        max_entries = self._positive_int(
            arguments.get("max_entries", 100),
            "max_entries",
        )
        all_entries = sorted(
            path.iterdir(),
            key=lambda item: item.name.lower(),
        )
        entries = all_entries[:max_entries]

        return {
            "path": self._relative_path(path),
            "entries": [
                {
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                }
                for item in entries
            ],
            "truncated": len(all_entries) > max_entries,
        }

    def _read_file_sync(self, arguments: Mapping[str, object]) -> object:
        path = self._resolve_path(arguments.get("path"))
        if not path.is_file():
            raise ValueError(f"Not a file: {self._relative_path(path)}")

        max_chars = self._positive_int(
            arguments.get("max_chars", 50_000),
            "max_chars",
        )
        content = path.read_text(encoding="utf-8")

        return {
            "path": self._relative_path(path),
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
        }

    def _search_text_sync(self, arguments: Mapping[str, object]) -> object:
        query = self._required_string(arguments.get("query"), "query")
        path = self._resolve_path(arguments.get("path", "."))
        max_results = self._positive_int(
            arguments.get("max_results", 100),
            "max_results",
        )

        candidates = (
            [path]
            if path.is_file()
            else sorted(path.rglob("*"), key=lambda item: str(item).lower())
        )
        matches: list[dict[str, object]] = []

        for candidate in candidates:
            if not candidate.is_file():
                continue

            try:
                lines = candidate.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue

            for line_number, line in enumerate(lines, start=1):
                if query in line:
                    matches.append(
                        {
                            "path": self._relative_path(candidate),
                            "line": line_number,
                            "text": line,
                        }
                    )
                    if len(matches) >= max_results:
                        return {
                            "query": query,
                            "matches": matches,
                            "truncated": True,
                        }

        return {
            "query": query,
            "matches": matches,
            "truncated": False,
        }

    def _resolve_path(self, value: object) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("path must be a non-empty string.")

        path = (self.root / value).resolve()

        try:
            path.relative_to(self.root)
        except ValueError as error:
            raise ValueError("path must stay inside the workspace.") from error

        return path

    def _relative_path(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix() or "."

    @staticmethod
    def _required_string(value: object, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string.")
        return value

    @staticmethod
    def _positive_int(value: object, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer.")
        return value


def build_read_only_registry(root: Path) -> ToolRegistry:
    """创建 M2 默认的三项只读工作区工具注册表。"""

    tools = ReadOnlyWorkspaceTools(root=root)
    registry = ToolRegistry()

    registry.register(
        ToolDefinition(
            name="list_files",
            description="列出工作区目录中的文件和子目录。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_entries": {"type": "integer"},
                },
            },
        ),
        tools.list_files,
    )
    registry.register(
        ToolDefinition(
            name="read_file",
            description="读取工作区内的 UTF-8 文本文件。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_chars": {"type": "integer"},
                },
                "required": ["path"],
            },
        ),
        tools.read_file,
    )
    registry.register(
        ToolDefinition(
            name="search_text",
            description="在工作区文本文件中搜索匹配行。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
            },
        ),
        tools.search_text,
    )

    return registry
