class OrchestratorExceedMaxIterationsException(RuntimeError):

    def __init__(self):
        super().__init__("Agent stopped due to max iterations.")
