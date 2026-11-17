from aidial_sdk.chat_completion import Role
from injector import ProviderOf, inject

from quickapp.common import REQUEST_MESSAGES
from quickapp.common.deferred_tool_types import DeferredToolDefinition
from quickapp.common.state_holder import StateHolder
from quickapp.core.agent.models import OpenAiToolConfigDict

# Key in an assistant message's `custom_content.state` holding the names of deferred tools
# discovered so far in the conversation, in discovery order.
DISCOVERED_TOOLS_STATE_KEY: str = "discovered_tools"


class LazyLoadedToolsHolder:
    """Request-scoped accumulator for tool schemas discovered via tool_search.

    _ToolSearchTool writes to this holder during execution.
    _ChatCompletionConfigBuilder reads from it on every build() call and merges
    the accumulated schemas into payload["tools"].
    ToolExecutor asks `contains` to reject calls to deferred tools whose schema is not loaded.

    The loaded tool names are mirrored into the response state after every change. The
    orchestrator sends the state to the client with the final assistant message, so the next
    turn restores the tools from it. Without deferred tools registered the holder stays empty
    and writes nothing.

    Tools discovered in earlier turns are restored on first use, not on construction: REST and
    internal tools register their deferred definitions while the tool list is being built, so
    the definitions are only complete by the time the holder is first read.
    """

    @inject
    def __init__(
        self,
        state_holder: StateHolder,
        request_messages: REQUEST_MESSAGES,
        definitions_provider: ProviderOf[list[DeferredToolDefinition]],
    ) -> None:
        self._tools: dict[str, OpenAiToolConfigDict] = {}
        self.__state_holder = state_holder
        self.__request_messages = request_messages
        self.__definitions_provider = definitions_provider
        self.__restored: bool = False

    def add(self, tools: list[OpenAiToolConfigDict]) -> None:
        self.__ensure_restored()
        self.__put(tools)
        self.__persist()

    def get_all(self) -> list[OpenAiToolConfigDict]:
        self.__ensure_restored()
        return list(self._tools.values())

    @property
    def names(self) -> list[str]:
        """Loaded tool names in discovery order."""
        self.__ensure_restored()
        return list(self._tools)

    def contains(self, name: str) -> bool:
        self.__ensure_restored()
        return name in self._tools

    def __put(self, tools: list[OpenAiToolConfigDict]) -> None:
        for tool in tools:
            name: str = tool.get("function", {}).get("name", "")
            if name:
                self._tools[name] = tool

    def __ensure_restored(self) -> None:
        """Reload tools discovered in earlier turns.

        Names that are no longer deferred (config changed, toolset removed) are dropped. The
        outcome is persisted even when empty, so the dropped names are not resurrected from an
        older message.
        """
        if self.__restored:
            return
        self.__restored = True
        stored_names = self.__read_stored_names()
        if not stored_names:
            return
        definitions_by_name = {d.name: d.definition for d in self.__definitions_provider.get()}
        self.__put([definitions_by_name[n] for n in stored_names if n in definitions_by_name])
        self.__persist()

    def __persist(self) -> None:
        self.__state_holder.add_state(DISCOVERED_TOOLS_STATE_KEY, list(self._tools))

    def __read_stored_names(self) -> list[str]:
        """Names of deferred tools discovered in earlier turns, in discovery order.

        Every turn that discovered or restored tools writes the full accumulated list on its
        final assistant message, so the latest assistant message that carries the key is
        authoritative. Malformed values are ignored.
        """
        for message in reversed(self.__request_messages):
            if message.role != Role.ASSISTANT or not message.custom_content:
                continue
            state = message.custom_content.state
            if not isinstance(state, dict) or DISCOVERED_TOOLS_STATE_KEY not in state:
                continue
            stored = state[DISCOVERED_TOOLS_STATE_KEY]
            if not isinstance(stored, list):
                return []
            return [name for name in stored if isinstance(name, str) and name]
        return []
