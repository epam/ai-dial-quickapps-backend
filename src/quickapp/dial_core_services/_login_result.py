from enum import Enum


class LoginResult(Enum):
    """Outcome of an interactive login request for a single toolset."""

    SUCCESS = "success"
    DENIED = "denied"
    TIMEOUT = "timeout"
    ERROR = "error"
    NO_CHANNEL = "no_channel"
