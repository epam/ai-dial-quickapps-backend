from quickapp.common.exceptions.tool_error import ToolErrorException


class MCPToolErrorException(ToolErrorException):
    """Raised when an MCP tool call returns isError=True.

    Inherits the base's structural ``__str__`` (no response body) so the failure's
    log/traceback records honor the content rule; the body stays on ``error_message`` for
    the LLM/user channels.
    """

    tool_kind = "MCP tool"
