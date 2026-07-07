from quickapp.common.exceptions.tool_error import ToolErrorException


class RestApiToolErrorException(ToolErrorException):
    """Raised when a REST API tool call returns a non-success HTTP status."""

    def __str__(self) -> str:
        return f"REST API tool '{self.tool_name}' returned an error: {self.error_message}"
