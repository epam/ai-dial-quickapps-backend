class ChatStreamHandlerError(Exception):
    """Base class for chat stream handler failures."""


class ChatStreamParseError(ChatStreamHandlerError):
    """Raised when a stream chunk cannot be parsed."""


class ChatStreamWriteError(ChatStreamHandlerError):
    """Raised when writing streamed output to a sink fails."""
