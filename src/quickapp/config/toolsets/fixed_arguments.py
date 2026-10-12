from typing import Any

FIXED_ARGUMENTS_DESCRIPTION = (
    "Argument values fixed per MCP tool, keyed by tool name (as the server reports it): "
    "{tool_name: {argument: value}}. Fixed arguments are removed from the schema the model sees "
    "and added to every call, overriding any value the caller sends. Top-level arguments only. "
    "When allowed_tools is set, every key must be listed there. Values are stored in plain text "
    "in the app config: do not use this for secrets."
)


def validate_fixed_arguments(
    allowed_tools: list[str] | None, fixed_arguments: dict[str, dict[str, Any]] | None
) -> None:
    """Reject ``fixed_arguments`` keys that ``allowed_tools`` would drop before routing."""
    if not fixed_arguments or not allowed_tools:
        return
    missing = [name for name in fixed_arguments if name not in allowed_tools]
    if missing:
        raise ValueError(
            f"fixed_arguments entries not present in allowed_tools: {', '.join(missing)}"
        )
