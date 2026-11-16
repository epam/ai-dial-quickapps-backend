from aidial_sdk.chat_completion import Message, Role

from quickapp.core.agent.models import DISCOVERED_TOOLS


def read_discovered_tool_names(messages: list[Message]) -> list[str]:
    """Names of deferred tools discovered in earlier turns, in discovery order.

    Each turn persists the full accumulated list on its final assistant message, so the latest
    assistant message that carries the key is authoritative. Malformed values are ignored.
    """
    for message in reversed(messages):
        if message.role != Role.ASSISTANT or not message.custom_content:
            continue
        state = message.custom_content.state
        if not isinstance(state, dict) or DISCOVERED_TOOLS not in state:
            continue
        stored = state[DISCOVERED_TOOLS]
        if not isinstance(stored, list):
            return []
        return [name for name in stored if isinstance(name, str) and name]
    return []
