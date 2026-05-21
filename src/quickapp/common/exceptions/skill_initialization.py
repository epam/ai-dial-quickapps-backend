from typing import ClassVar, Literal

from .initialization import InitializationException

SkillIssueSeverity = Literal["error", "warning"]


class SkillInitializationException(InitializationException):
    """Per-URL skill-loading issue — fetch error, invalid frontmatter,
    duplicate name, predefined-vs-external name collision, or a non-fatal
    parser warning. Soft by default: the request proceeds with whatever
    skills did resolve. ``severity`` drives the renderer's section split.
    """

    is_hard: ClassVar[bool] = False

    def __init__(
        self,
        reason: str,
        url: str | None = None,
        severity: SkillIssueSeverity = "error",
    ):
        super().__init__(reason if url is None else f"{url}: {reason}")
        self.reason = reason
        self.url = url
        self.severity: SkillIssueSeverity = severity


class SkillCatastrophicInitializationException(SkillInitializationException):
    """Whole-subsystem skill-loading failure (e.g. resolver raised before any
    per-URL task ran). Hard: flips the Initialization issues stage to FAILED.
    """

    is_hard: ClassVar[bool] = True

    def __init__(self, reason: str):
        super().__init__(reason, url=None)
