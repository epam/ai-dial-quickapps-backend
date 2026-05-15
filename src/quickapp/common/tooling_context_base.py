import threading

from aidial_sdk.chat_completion.request import StaticTool

from quickapp.common import StagedBaseTool

from .exceptions import InitializationException, ToolInitializationException


class ToolingContextBase:
    """Base class for tooling context."""

    def __init__(self):
        self._tools: list[StagedBaseTool] = []
        self._static_tools: list[StaticTool] = []
        self._exceptions: list[InitializationException] = []
        self._lock = threading.Lock()

    def append_tool(self, tool: StagedBaseTool) -> None:
        with self._lock:
            self._tools.append(tool)

    def extend_tools(self, tools: list[StagedBaseTool]) -> None:
        with self._lock:
            self._tools.extend(tools)

    def append_default_tool(self, tool: StaticTool) -> None:
        with self._lock:
            self._static_tools.append(tool)

    def extend_static_tools(self, tools: list[StaticTool]) -> None:
        with self._lock:
            self._static_tools.extend(tools)

    @property
    def tools(self) -> list[StagedBaseTool]:
        return self._tools

    @property
    def static_tools(self) -> list[StaticTool]:
        return self._static_tools

    @property
    def exceptions(self) -> list[InitializationException]:
        return self._exceptions

    def append_exception(self, exception: ToolInitializationException) -> None:
        with self._lock:
            self._exceptions.append(exception)
