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
