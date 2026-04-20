class OrchestratorExceedMaxIterationsException(RuntimeError):

    def __init__(self):
        self.message = "Agent stopped due to max iterations."

    def __str__(self):
        return self.message


class InvalidToolCallParameterException(ValueError):

    def __init__(self, parameter_name: str, message: str):
        self.parameter_name = parameter_name
        self.message = message

    def __str__(self):
        return self.message


TOOL_TIMEOUT_PHRASE = "timed out"
"""Stable substring present in every timeout-related user-facing message.

Load-bearing: `TriggerOn(type=contains, value=TOOL_TIMEOUT_PHRASE)` in tool
fallback configuration relies on this appearing in both
`ToolTimeoutError.__str__` (stage UI short form) and the long LLM-facing
message emitted by `FallbackProcessor._process_timeout`.
"""


class ToolTimeoutError(RuntimeError):
    """Raised when a tool invocation exceeds its configured timeout."""

    def __init__(self, tool_name: str, timeout_seconds: float):
        self.tool_name = tool_name
        self.timeout_seconds = timeout_seconds
        self.message = (
            f"Tool call '{tool_name}' {TOOL_TIMEOUT_PHRASE} after {timeout_seconds} seconds."
        )
        super().__init__(self.message)

    def __str__(self):
        return self.message
