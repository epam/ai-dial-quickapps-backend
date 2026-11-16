from quickapp.core.agent.models import OpenAiToolConfigDict


class LazyLoadedToolsHolder:
    """Request-scoped accumulator for tool schemas discovered via tool_search.

    _ToolSearchTool writes to this holder during execution.
    _ChatCompletionConfigBuilder reads from it on every build() call and merges
    the accumulated schemas into payload["tools"].
    ToolExecutor asks `contains` to reject calls to deferred tools whose schema is not loaded.
    Bound by ToolDiscoveryModule, which also carries its content across turns.
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

    @property
    def names(self) -> list[str]:
        """Loaded tool names in discovery order."""
        return list(self._tools)

    def contains(self, name: str) -> bool:
        return name in self._tools
