from .initialization import InitializationException


class OrchestratorInitializationException(InitializationException):
    """Raised when the orchestrator deployment (the application's primary LLM)
    cannot be initialized — typically because its DIAL Core metadata is missing
    or unreachable. The request cannot proceed without an orchestrator.
    """

    def __init__(self, message: str, deployment_id: str):
        super().__init__(
            f"Orchestrator initialization error: {message} (deployment_id={deployment_id})"
        )
        self.message = message
        self.deployment_id = deployment_id
