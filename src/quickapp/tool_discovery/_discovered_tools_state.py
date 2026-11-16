from aidial_sdk.chat_completion import Message, Role

# Key in an assistant message's `custom_content.state` holding the names of deferred tools
# discovered so far in the conversation, in discovery order.
DISCOVERED_TOOLS_STATE_KEY: str = "discovered_tools"


def read_discovered_tool_names(messages: list[Message]) -> list[str]:
    """Names of deferred tools discovered in earlier turns, in discovery order.

    Every turn that discovered or restored tools writes the full accumulated list on its final
    assistant message, so the latest assistant message that carries the key is authoritative.
    Malformed values are ignored.
    """
    for message in reversed(messages):
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
