from quickapp.common.exceptions.tool_error import ToolErrorException


class DialFilesToolErrorException(ToolErrorException):
    """Raised when a file operation with valid arguments failed and an immediate retry
    won't help (e.g. a move that left both files).

    Not a bad-parameter case: the message is forwarded to the model/user via the
    tool's fallback configuration, without the "fix the parameter and retry" framing.
    """

    tool_kind = "DIAL files tool"
