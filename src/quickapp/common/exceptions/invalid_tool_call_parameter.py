# Every one of these messages is fed back to the model as a retry instruction
# (StagedBaseTool.__run_tool_body) and rendered into the tool stage, so an oversized
# rejected argument would otherwise overflow the next orchestrator request (issue #578).
# Call sites still sanitize the value they interpolate; this is the backstop for the
# ones that forget, or that embed something other than a URL.
_MAX_MESSAGE_LENGTH = 1000


class InvalidToolCallParameterException(ValueError):

    def __init__(self, parameter_name: str, message: str):
        if len(message) > _MAX_MESSAGE_LENGTH:
            message = f"{message[:_MAX_MESSAGE_LENGTH]}…(truncated, {len(message)} chars)"
        super().__init__(message)
        self.parameter_name = parameter_name
        self.message = message
