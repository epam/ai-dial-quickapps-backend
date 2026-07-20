from quickapp.common.exceptions.tool_error import ToolErrorException


class RestApiToolErrorException(ToolErrorException):
    """Raised when a REST API tool call returns a non-success HTTP status.

    Inherits the base's structural ``__str__``; the (already status-only) ``error_message``
    stays available for the LLM/user channels.
    """

    tool_kind = "REST API tool"
