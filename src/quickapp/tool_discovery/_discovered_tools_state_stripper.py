from aidial_sdk.chat_completion import Message

from quickapp.common.abstract.base_transformer import PreInvocationTransformer
from quickapp.tool_discovery._discovered_tools_state import DISCOVERED_TOOLS_STATE_KEY


class _DiscoveredToolsStateStripper(PreInvocationTransformer):
    """Hides the `discovered_tools` bookkeeping from the orchestrator model.

    The key only matters to QuickApps; it is removed from copies of the affected messages, the
    canonical history keeps it. The orchestrator deployment receives messages verbatim, and if it
    is itself a QuickApp it would read the key and load its own deferred tools from it, so the key
    must not leave this app.
    """

    def transform(self, messages: list[Message]) -> list[Message]:
        return [self.__strip(message) for message in messages]

    @staticmethod
    def __strip(message: Message) -> Message:
        custom = message.custom_content
        if custom is None or not isinstance(custom.state, dict):
            return message
        if DISCOVERED_TOOLS_STATE_KEY not in custom.state:
            return message
        state = {k: v for k, v in custom.state.items() if k != DISCOVERED_TOOLS_STATE_KEY}
        stripped = custom.model_copy(update={"state": state or None})
        has_content = stripped.model_dump(exclude_none=True) != {}
        return message.model_copy(update={"custom_content": stripped if has_content else None})
