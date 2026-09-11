from injector import inject

from quickapp.core.agent.models import OpenAiToolConfigDict


@inject
class LazyLoadedToolsHolder:
    """Request-scoped accumulator for tool schemas discovered via tool_search.

    _ToolSearchTool writes to this holder during execution.
    _ChatCompletionConfigBuilder reads from it on every build() call and merges
    the accumulated schemas into payload["tools"].
    """

    def __init__(self) -> None:
        self._tools: dict[str, OpenAiToolConfigDict] = {}

    def add(self, tools: list[OpenAiToolConfigDict]) -> None:
        for tool in tools:
            name: str = tool.get("function", {}).get("name", "")
            if name:
                self._tools[name] = tool

    def get_all(self) -> list[OpenAiToolConfigDict]:
        return list(self._tools.values())
