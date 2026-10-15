HIDDEN_FROM_MODEL_DESCRIPTION = (
    "MCP tool names (as the server reports them) that hooks can call but the model never sees: "
    "they are absent from the tools payload and the tool_search catalog, and are not executed "
    "if the model requests them. When allowed_tools is set, every entry must be listed there. "
    "Tools added to the server later stay visible to the model unless allowed_tools pins the set."
)
