from typing import ClassVar

from .initialization import InitializationException


class ProjectInstructionsException(InitializationException):
    """The project's PROJECT.md could not be loaded. Soft: the turn runs without the
    project instructions; rendered as a warning in the Initialization issues stage."""

    is_hard: ClassVar[bool] = False

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(
            f"PROJECT.md could not be loaded ({reason}); this answer doesn't follow the "
            "project instructions."
        )
