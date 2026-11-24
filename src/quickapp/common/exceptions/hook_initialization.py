from .initialization import InitializationException, InitializationIssueLevel


class HookInitializationException(InitializationException):
    """Raised when a hook references a tool not found in the initialized tools list."""

    level = InitializationIssueLevel.ERROR

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
