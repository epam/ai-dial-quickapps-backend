from enum import Enum


class InitializationIssueLevel(str, Enum):
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class InitializationException(Exception):
    """Base class for any failure that should flow through the merged
    ``list[InitializationException]`` multiprovider to
    ``_InitializationErrorHandler`` for unified rendering.

    ``level`` only drives display (threshold filter, stage status, skill section
    split); whether the request stops is decided by raising vs. recording.

    ``str()`` must stay log-safe (CODESTYLE §9); ``user_facing_message`` is the
    stage text.
    """

    level: InitializationIssueLevel = InitializationIssueLevel.CRITICAL

    @property
    def user_facing_message(self) -> str:
        return str(self)
