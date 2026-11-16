from quickapp.core.agent.models import OpenAiToolConfigDict


class LazyLoadedToolsHolder:
    """Request-scoped accumulator for tool schemas discovered via tool_search.

    Seeded at request start with the tools discovered in earlier turns of the conversation,
    then extended by _ToolSearchTool during execution.
    _ChatCompletionConfigBuilder reads from it on every build() call and merges
    the accumulated schemas into payload["tools"]; the Orchestrator persists `names`
    into the response state for the next turn.
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
