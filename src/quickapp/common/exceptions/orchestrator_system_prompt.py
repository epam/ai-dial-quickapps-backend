from .initialization import InitializationException


class OrchestratorSystemPromptException(InitializationException):
    """The orchestrator's `dial` system prompt could not be loaded.
    The request fails rather than run with an empty prompt.
    """

    def __init__(self, message: str, path: str):
        super().__init__(f"System prompt '{path}' could not be loaded: {message}")
