import logging
from typing import Any

from quickapp.common.dial_request_fields import CUSTOM_FIELDS
from quickapp.core.agent.models import OpenAiToolConfigDict

logger = logging.getLogger(__name__)

_CACHE_BREAKPOINT = "cache_breakpoint"

# Anthropic allows 4 breakpoints per request; one slot stays free for a request-level
# breakpoint an admin may preset through Core `defaults`, which QuickApps cannot see.
_MAX_BREAKPOINTS = 3


class _PromptCacheBreakpoints:
    """Marks the system message, the last message and the last function tool with
    ``custom_fields.cache_breakpoint``, in that order, while slots remain. Marked items are
    replaced by copies; client breakpoints are counted, not removed.
    """

    def apply(self, messages: list[dict[str, Any]], tools: list[OpenAiToolConfigDict]) -> None:
        free = _MAX_BREAKPOINTS - sum(1 for item in [*messages, *tools] if _has_breakpoint(item))
        placed: list[str] = []
        for label, items, index in _targets(messages, tools):
            if len(placed) >= free:
                break
            if _has_breakpoint(items[index]):
                continue
            item = items[index]
            items[index] = {
                **item,
                CUSTOM_FIELDS: {**(item.get(CUSTOM_FIELDS) or {}), _CACHE_BREAKPOINT: {}},
            }
            placed.append(label)
        logger.debug("Prompt cache breakpoints placed on %s", placed or "nothing")


def _targets(
    messages: list[dict[str, Any]], tools: list[OpenAiToolConfigDict]
) -> list[tuple[str, list[dict[str, Any]], int]]:
    has_system = bool(messages) and messages[0].get("role") == "system"
    targets: list[tuple[str, list[dict[str, Any]], int]] = []
    if has_system:
        targets.append(("messages[0]", messages, 0))
    if len(messages) > (1 if has_system else 0):
        targets.append(("messages[-1]", messages, len(messages) - 1))
    # Static tools have no ``custom_fields`` in the SDK schema; adapters would reject one.
    last_function = next(
        (i for i in reversed(range(len(tools))) if tools[i].get("type") == "function"), None
    )
    if last_function is not None:
        targets.append((f"tools[{last_function}]", tools, last_function))
    return targets


def _has_breakpoint(item: dict[str, Any]) -> bool:
    custom_fields = item.get(CUSTOM_FIELDS)
    return isinstance(custom_fields, dict) and _CACHE_BREAKPOINT in custom_fields
