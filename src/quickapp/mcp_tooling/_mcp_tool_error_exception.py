class MCPToolErrorException(Exception):
    """Raised when an MCP tool call returns isError=True."""

    def __init__(self, tool_name: str, error_message: str):
        super().__init__(f"MCP tool '{tool_name}' returned an error: {error_message}")
        self.tool_name = tool_name
        self.error_message = error_message
