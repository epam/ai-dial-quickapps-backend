from .initialization import InitializationException, InitializationIssueLevel


class SkillInitializationException(InitializationException):
    """Per-URL skill-loading issue — fetch error, invalid frontmatter,
    duplicate name, predefined-vs-external name collision, or a warning
    (bundled files couldn't be listed). The request proceeds with whatever
    skills did resolve. ``level`` also drives the renderer's section split.
    """

    def __init__(
        self,
        reason: str,
        url: str | None = None,
        level: InitializationIssueLevel = InitializationIssueLevel.ERROR,
    ):
        super().__init__(reason if url is None else f"{url}: {reason}")
        self.reason = reason
        self.url = url
        self.level = level


class SkillCatastrophicInitializationException(SkillInitializationException):
    """Whole-subsystem skill-loading failure (e.g. resolver raised before any
    per-URL task ran). Critical: flips the Initialization issues stage to FAILED.
    """

    def __init__(self, reason: str):
        super().__init__(reason, url=None, level=InitializationIssueLevel.CRITICAL)
