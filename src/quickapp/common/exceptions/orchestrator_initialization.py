from typing import ClassVar

from .initialization import InitializationException


class OrchestratorInitializationException(InitializationException):
    """Raised when the orchestrator deployment (the application's primary LLM)
    cannot be initialized — typically because its DIAL Core metadata is missing
    or unreachable. Hard: the request cannot proceed without an orchestrator.
    """

    is_hard: ClassVar[bool] = True

    def __init__(self, message: str, deployment_id: str):
        super().__init__(
            f"Orchestrator initialization error: {message} (deployment_id={deployment_id})"
        )
        self.message = message
        self.deployment_id = deployment_id
