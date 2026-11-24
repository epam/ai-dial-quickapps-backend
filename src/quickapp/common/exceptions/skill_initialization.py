from quickapp.common.url_sanitization import sanitize_url

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
        # reason is free text (may carry a fetch error's URL), so it stays out of str().
        super().__init__("Skill issue" if url is None else f"Skill issue at {sanitize_url(url)}")
        self.reason = reason
        self.url = url
        self.level = level

    @property
    def user_facing_message(self) -> str:
        if self.url is None:
            return self.reason
        return f"**{sanitize_url(self.url)}**: {self.reason}"


class SkillCatastrophicInitializationException(SkillInitializationException):
    """Whole-subsystem skill-loading failure (e.g. resolver raised before any
    per-URL task ran). Critical: flips the Initialization issues stage to FAILED.
    """

    def __init__(self, reason: str):
        super().__init__(reason, url=None, level=InitializationIssueLevel.CRITICAL)
