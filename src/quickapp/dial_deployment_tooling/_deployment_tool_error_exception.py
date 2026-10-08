from quickapp.common.exception_message_resolver import ResolvedError
from quickapp.common.exceptions.tool_error import ToolErrorException


class DeploymentToolErrorException(ToolErrorException):
    """Raised when the downstream DIAL deployment rejects a tool call.

    ``error_message`` carries the resolver's user-safe text plus the status code, never the
    raw upstream body, so the stage, the LLM and ``trigger_on`` all see the same cause.
    """

    tool_kind = "Deployment tool"

    def __init__(self, tool_name: str, resolved: ResolvedError):
        status_code = resolved.details.status_code
        error_message = resolved.message
        if status_code is not None:
            error_message = f"{error_message} (status code: {status_code})"
        super().__init__(tool_name, error_message)
