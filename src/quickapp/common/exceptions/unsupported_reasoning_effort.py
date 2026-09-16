from typing import ClassVar

from .initialization import InitializationException


class UnsupportedReasoningEffortException(InitializationException):
    """The configured ``reasoning_effort`` is not one the orchestrator deployment
    advertises in ``features.reasoningEfforts``, so it was dropped from the model
    call. Soft: the request proceeds without it, rendered as a warning in the
    Initialization issues stage.

    Dropping is preferred over passing the value through because a deployment that
    does not support it answers with an opaque ``400`` that reaches the user as a
    generic "request was rejected as invalid" error.
    """

    is_hard: ClassVar[bool] = False

    def __init__(self, requested: str, supported: list[str]):
        self.requested = requested
        self.supported = supported
        # The deployment is deliberately not named: which model an application runs on is
        # not the end user's business, and every other user-facing message about it says
        # "the AI model configured in this application" (`_exception_message_resolver`).
        if supported:
            advertised = "supports " + ", ".join(f"`{value}`" for value in supported)
        else:
            advertised = "does not advertise support for `reasoning_effort`"
        super().__init__(
            f"The AI model configured in this application {advertised}, so the configured "
            f"`reasoning_effort={requested}` was dropped from the request."
        )
