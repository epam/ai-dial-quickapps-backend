from quickapp.common.exceptions.tool_error import ToolErrorException


class MCPToolErrorException(ToolErrorException):
    """Raised when an MCP tool call returns isError=True."""

    def __str__(self) -> str:
        return f"MCP tool '{self.tool_name}' returned an error: {self.error_message}"

