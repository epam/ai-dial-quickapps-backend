import threading

from quickapp.common import StagedBaseTool

from .exceptions import ToolInitializationException


class ToolingContextBase:
    """Base class for tooling context."""

    def __init__(self):
        self._tools: list[StagedBaseTool] = []
        self._exceptions: list[ToolInitializationException] = []
        self._lock = threading.Lock()

    def append_tool(self, tool: StagedBaseTool) -> None:
        with self._lock:
            self._tools.append(tool)

    def extend_tools(self, tools: list[StagedBaseTool]) -> None:
        with self._lock:
            self._tools.extend(tools)

    @property
    def tools(self) -> list[StagedBaseTool]:
        return self._tools

    @property
    def exceptions(self) -> list[ToolInitializationException]:
        return self._exceptions

    def append_exception(self, exception: ToolInitializationException) -> None:
        with self._lock:
            self._exceptions.append(exception)
