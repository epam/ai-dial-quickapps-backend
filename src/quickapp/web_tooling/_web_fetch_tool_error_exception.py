from quickapp.common.exceptions.tool_error import ToolErrorException


class WebFetchToolErrorException(ToolErrorException):
    """Raised when a fetch fails for a valid URL (egress denied, size, timeout,
    transport, or a non-text body on an inline read).

    Not a bad-parameter case: the URL is correct, so this is a tool error whose
    message is forwarded to the model/user via the tool's fallback configuration.
    """

    tool_kind = "Web fetch tool"
