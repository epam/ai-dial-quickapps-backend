from injector import ProviderOf, inject

from quickapp.common import REQUEST_MESSAGES
from quickapp.common.deferred_tool_types import DeferredToolDefinition
from quickapp.common.state_holder import StateHolder
from quickapp.config.tools.base import OpenAiToolConfigDict
from quickapp.core.agent.lazy_loaded_tools_holder import LazyLoadedToolsHolder
from quickapp.tool_discovery._discovered_tools_state import (
    DISCOVERED_TOOLS_STATE_KEY,
    read_discovered_tool_names,
)


class _PersistedToolsHolder(LazyLoadedToolsHolder):
    """Holder that mirrors the loaded tool names into the response state after every change.

    The orchestrator sends the state to the client with the final assistant message, so the
    next turn can restore the tools (see `read_discovered_tool_names`).

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
        super().__init__()
        self.__state_holder: StateHolder = state_holder
        self.__request_messages = request_messages
        self.__definitions_provider = definitions_provider
        self.__restored: bool = False

    def add(self, tools: list[OpenAiToolConfigDict]) -> None:
        self.__ensure_restored()
        super().add(tools)
        self.__persist()

    def get_all(self) -> list[OpenAiToolConfigDict]:
        self.__ensure_restored()
        return super().get_all()

    @property
    def names(self) -> list[str]:
        self.__ensure_restored()
        return super().names

    def contains(self, name: str) -> bool:
        self.__ensure_restored()
        return super().contains(name)

    def __ensure_restored(self) -> None:
        """Reload tools discovered in earlier turns.

        Names that are no longer deferred (config changed, toolset removed) are dropped. The
        outcome is persisted even when empty, so the dropped names are not resurrected from an
        older message.
        """
        if self.__restored:
            return
        self.__restored = True
        stored_names = read_discovered_tool_names(self.__request_messages)
        if not stored_names:
            return
        definitions_by_name = {d.name: d.definition for d in self.__definitions_provider.get()}
        super().add([definitions_by_name[n] for n in stored_names if n in definitions_by_name])
        self.__persist()

    def __persist(self) -> None:
        self.__state_holder.add_state(DISCOVERED_TOOLS_STATE_KEY, super().names)
