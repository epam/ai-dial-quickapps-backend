from __future__ import annotations


class ChatStreamHandlerError(Exception):
    """Base class for chat stream handler failures."""


class ChatStreamParseError(ChatStreamHandlerError):
    """Raised when a stream chunk cannot be parsed."""


class ChatStreamSinkWriteError(ChatStreamHandlerError):
    """Raised when writing streamed output to a sink fails."""


class ChatStreamInvariantError(ChatStreamHandlerError):
    """Raised when handler detects an invalid internal state."""
