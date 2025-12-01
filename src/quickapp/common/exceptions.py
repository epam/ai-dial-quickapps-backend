class OrchestratorExceedMaxIterationsException(RuntimeError):

    def __init__(self):
        self.message = "Agent stopped due to max iterations."

    def __str__(self):
        return self.message
