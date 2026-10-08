HIDDEN_FROM_MODEL_DESCRIPTION = (
    "MCP tool names (as the server reports them) that hooks can call but the model never sees: "
    "they are absent from the tools payload and the tool_search catalog, and are not executed "
    "if the model requests them. When allowed_tools is set, every entry must be listed there. "
    "Tools added to the server later stay visible to the model unless allowed_tools pins the set."
)


def validate_hidden_from_model(
    allowed_tools: list[str] | None, hidden_from_model: list[str] | None
) -> None:
    """Reject ``hidden_from_model`` entries that ``allowed_tools`` would drop before routing."""
    if not hidden_from_model or not allowed_tools:
        return
    missing = [name for name in hidden_from_model if name not in allowed_tools]
    if missing:
        raise ValueError(
            f"hidden_from_model entries not present in allowed_tools: {', '.join(missing)}"
        )
