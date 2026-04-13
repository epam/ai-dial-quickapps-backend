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


class ToolTimeoutError(RuntimeError):
    """Raised when a tool invocation exceeds its configured timeout.

    The string representation always contains the stable phrase ``"timed out"`` so
    that ``TriggerOn(type=contains, value="timed out")`` can match it in tool
    fallback configuration.
    """

    def __init__(self, tool_name: str, timeout_seconds: float):
        self.tool_name = tool_name
        self.timeout_seconds = timeout_seconds
        self.message = f"Tool call '{tool_name}' timed out after {timeout_seconds} seconds."
        super().__init__(self.message)

    def __str__(self):
        return self.message
