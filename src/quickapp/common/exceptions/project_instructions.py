from .initialization import InitializationException, InitializationIssueLevel


class ProjectInstructionsException(InitializationException):
    """The project's PROJECT.md could not be loaded. The turn runs without the
    project instructions."""

    level = InitializationIssueLevel.ERROR

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(
            f"PROJECT.md could not be loaded ({reason}); this answer doesn't follow the "
            "project instructions."
        )
