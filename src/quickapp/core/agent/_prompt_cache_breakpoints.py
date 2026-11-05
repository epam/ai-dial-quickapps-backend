import logging
from typing import Any

from quickapp.common.dial_request_fields import CUSTOM_FIELDS
from quickapp.core.agent.models import OpenAiToolConfigDict

logger = logging.getLogger(__name__)

_CACHE_BREAKPOINT = "cache_breakpoint"


class _PromptCacheBreakpoints:
    """Marks the system message, the last message and the last function tool with
    ``custom_fields.cache_breakpoint``. Marked items are replaced by copies.
    """

    def apply(self, messages: list[dict[str, Any]], tools: list[OpenAiToolConfigDict]) -> None:
        placed: list[str] = []
        for i in _message_indexes_to_mark(messages):
            messages[i] = _copy_with_breakpoint(messages[i])
            placed.append(f"messages[{i}]")
        if (tool_index := _last_function_tool(tools)) is not None:
            tools[tool_index] = _copy_with_breakpoint(tools[tool_index])
            placed.append(f"tools[{tool_index}]")
        logger.debug("Prompt cache breakpoints placed on %s", placed or "nothing")


def _message_indexes_to_mark(messages: list[dict[str, Any]]) -> list[int]:
    """Indexes of the system message (when it opens the list) and of the last message.

    [system, user, assistant, user] -> [0, 3]
    [user, assistant, user]         -> [2]   no system message
    [system]                        -> [0]   the system message is also the last one
    """
    last = len(messages) - 1
    starts_with_system = messages[0].get("role") == "system"
    if starts_with_system and last > 0:
        return [0, last]
    return [last]


def _last_function_tool(tools: list[OpenAiToolConfigDict]) -> int | None:
    # Static tools have no ``custom_fields`` in the SDK schema; adapters would reject one.
    functions = [i for i, tool in enumerate(tools) if tool.get("type") == "function"]
    return functions[-1] if functions else None


def _copy_with_breakpoint(item: dict[str, Any]) -> dict[str, Any]:
    """Returns a copy of a message or tool with ``cache_breakpoint`` added to its
    ``custom_fields``. ``item`` itself is not changed, because it is shared across
    orchestrator iterations.

    {"role": "user", "content": "Hi"} ->
    {"role": "user", "content": "Hi", "custom_fields": {"cache_breakpoint": {}}}
    """
    custom_fields = {**(item.get(CUSTOM_FIELDS) or {}), _CACHE_BREAKPOINT: {}}
    return {**item, CUSTOM_FIELDS: custom_fields}
