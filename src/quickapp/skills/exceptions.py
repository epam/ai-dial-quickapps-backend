from collections.abc import Sequence


class SkillValidationError(Exception):
    """Raised by ``parse_frontmatter`` when skill content is invalid."""

    def __init__(self, source_id: str, reason: str) -> None:
        self.source_id = source_id
        self.reason = reason
        super().__init__(f"Skill validation failed for '{source_id}': {reason}")


class SkillFilesNotSupportedError(FileNotFoundError):
    """Raised when a ``file_path`` is asked of a skill source that has no files.

    Predefined and DIAL-prompt skills are single documents. Subclasses
    ``FileNotFoundError`` so the reader tool's existing handler renders the
    message to the model unchanged.
    """

    def __init__(self, skill_name: str) -> None:
        super().__init__(
            f"Skill '{skill_name}' has no bundled files."
            " Call read_skill without file_path to read its instructions."
        )


class SkillFileNotFoundError(FileNotFoundError):
    """Raised when a ``file_path`` is not among a skill's advertised files.

    Carries the inventory so the model can correct itself on the next turn
    instead of guessing again.
    """

    def __init__(self, skill_name: str, file_path: str, available: Sequence[str]) -> None:
        message = f"File '{file_path}' is not available in skill '{skill_name}'."
        if available:
            message += " Available files: " + ", ".join(available)
        else:
            message += " This skill has no readable bundled files."
        super().__init__(message)
