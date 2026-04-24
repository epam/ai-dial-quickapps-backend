from typing import ClassVar

from .initialization import InitializationException


class SkillInitializationException(InitializationException):
    """Per-URL skill-loading failure — fetch error, invalid frontmatter,
    duplicate name, or predefined-vs-external name collision. Soft by default:
    the request proceeds with whatever skills did resolve.
    """

    is_hard: ClassVar[bool] = False

    def __init__(self, reason: str, url: str | None = None):
        super().__init__(reason if url is None else f"{url}: {reason}")
        self.reason = reason
        self.url = url


class SkillCatastrophicInitializationException(SkillInitializationException):
    """Whole-subsystem skill-loading failure (e.g. resolver raised before any
    per-URL task ran). Hard: flips the Initialization issues stage to FAILED.
    """

    is_hard: ClassVar[bool] = True

    def __init__(self, reason: str):
        super().__init__(reason, url=None)
