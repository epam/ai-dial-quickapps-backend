class ToolErrorException(Exception):
    """Raised when a tool call returns an error.

    The exception *message* (``str(e)``, used in logs and tracebacks) carries only
    structure — the content rule (issue #436) keeps the tool response body out of the log
    pipeline. The body stays available on the :attr:`error_message` attribute, which the
    fallback machinery may forward to the LLM (``forward_tool_error_message``, #408) and
    the user channels (stage UI, error resolver) render via
    :attr:`user_facing_message`; none of these is a log channel.

    The structural string form is owned here so no subclass can accidentally embed the
    body: subclasses set :attr:`tool_kind` (the human label) and the base builds the
    message. ``str(e)`` returns this message (the sole ``Exception`` arg), so logs and
    tracebacks never carry the body.
    """

    tool_kind = "Tool"

    def __init__(self, tool_name: str, error_message: str):
        super().__init__(
            f"{self.tool_kind} '{tool_name}' returned an error "
            f"(content_length={len(error_message)})"
        )
        self.tool_name = tool_name
        self.error_message = error_message

    @property
    def user_facing_message(self) -> str:
        """User-facing rendering, body included; see the class docstring."""
        return f"{self.tool_kind} '{self.tool_name}' returned an error: {self.error_message}"
