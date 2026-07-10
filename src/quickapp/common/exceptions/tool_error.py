class ToolErrorException(Exception):
    """Raised when a tool call returns an error."""

    def __init__(self, tool_name: str, error_message: str):
        super().__init__(f"Tool '{tool_name}' returned an error: {error_message}")
        self.tool_name = tool_name
        self.error_message = error_message
