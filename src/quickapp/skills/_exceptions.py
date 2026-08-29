class SkillValidationError(Exception):
    """Raised by ``parse_frontmatter`` when skill content is invalid."""

    def __init__(self, source_id: str, reason: str) -> None:
        self.source_id = source_id
        self.reason = reason
        super().__init__(f"Skill validation failed for '{source_id}': {reason}")


class SkillFileError(Exception):
    """Base for the read-time failures ``Skill.read_file`` reports back to the agent.

    Source-neutral by design: a predefined skill's bundled file and a DIAL
    skill's bundled file fail the same way, so the reader tool renders one
    message regardless of provenance.
    """


class SkillFileNotFound(SkillFileError):
    """The requested path is not a readable file inside the skill."""


class SkillFileTooLarge(SkillFileError):
    """The file exceeds ``SKILLS_FILE_MAX_BYTES``.

    Refused rather than truncated: a half-file is worse than a clear failure
    for something the agent is about to follow as instructions.
    """

    def __init__(self, relative_path: str, size: int, limit: int) -> None:
        self.relative_path = relative_path
        self.size = size
        self.limit = limit
        super().__init__(
            f"'{relative_path}' is {size} bytes, over the {limit}-byte limit"
            " for a skill file; it was not read"
        )


class SkillFileNotText(SkillFileError):
    """The file is not decodable as UTF-8 text."""

    def __init__(self, relative_path: str, size: int) -> None:
        self.relative_path = relative_path
        self.size = size
        super().__init__(f"'{relative_path}' is a binary file, {size} bytes — not readable as text")
