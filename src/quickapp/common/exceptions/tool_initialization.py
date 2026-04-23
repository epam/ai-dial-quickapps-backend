class ToolInitializationException(Exception):
    """Raised when a tool or toolset fails to initialize properly."""

    def __init__(
        self, message: str, tool_name: str = "", toolset_name: str = "", details: str = ""
    ):
        super().__init__(
            f"Initialization Error: {message}" + (f" for Tool: {tool_name}" if tool_name else "")
        )
        self.message = message
        self.tool_name = tool_name
        self.toolset_name = toolset_name
        self.details = details
