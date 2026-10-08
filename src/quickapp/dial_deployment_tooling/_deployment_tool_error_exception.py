from quickapp.common.exception_message_resolver import ResolvedError
from quickapp.common.exceptions.tool_error import ToolErrorException


class DeploymentToolErrorException(ToolErrorException):
    """Raised when a tool call fails at the DIAL deployment or at its attachment lookup.

    ``error_message`` carries the resolver's user-safe text plus the status code, never the
    raw upstream body; the stage and the LLM see that. ``trigger_on`` also matches the raw
    ``upstream_message``, so rules written against the upstream wording keep matching.
    """

    tool_kind = "Deployment tool"

    def __init__(self, tool_name: str, resolved: ResolvedError, upstream_message: str):
        super().__init__(tool_name, resolved.message_with_status())
        self.upstream_message = upstream_message

    @property
    def trigger_texts(self) -> tuple[str, ...]:
        return (self.error_message, self.upstream_message)
