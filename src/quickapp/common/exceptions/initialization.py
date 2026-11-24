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
    """

    level: InitializationIssueLevel = InitializationIssueLevel.CRITICAL
