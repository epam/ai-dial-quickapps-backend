class InvalidToolCallParameterException(ValueError):

    def __init__(self, parameter_name: str, message: str):
        super().__init__(message)
        self.parameter_name = parameter_name
        self.message = message
