from typing import Any, ClassVar

from quickapp.common.exceptions.initialization import InitializationException


class UnsupportedDeploymentParameterException(InitializationException):
    """A configured request parameter the target deployment's DialCore features declare
    unsupported, so it was dropped from the model call (see
    ``quickapp.common.deployment_parameter_support``). Soft: the request proceeds without
    it, rendered as a warning in the Initialization issues stage.

    Dropping is preferred over passing the value through because a deployment that does
    not support it answers with an opaque ``400`` that reaches the user as a generic
    "request was rejected as invalid" error.
    """

    is_hard: ClassVar[bool] = False

    def __init__(self, parameter: str, value: Any, reason: str, tool_name: str | None = None):
        self.parameter = parameter
        self.value = value
        self.reason = reason
        self.tool_name = tool_name
        # The deployment is deliberately not named: which model an application runs on is
        # not the end user's business, and every other user-facing message about it says
        # "the AI model configured in this application" (`_exception_message_resolver`).
        subject = (
            "The AI model configured in this application"
            if tool_name is None
            else "The deployment this tool calls"
        )
        super().__init__(
            f"{subject} {reason}, so the configured `{parameter}={value}` was dropped "
            "from the request."
        )
