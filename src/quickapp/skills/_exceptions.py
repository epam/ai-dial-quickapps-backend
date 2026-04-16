from __future__ import annotations

from dataclasses import dataclass


class SkillValidationError(Exception):
    """Raised by ``parse_frontmatter`` when skill content is invalid."""

    def __init__(self, source_id: str, reason: str) -> None:
        self.source_id = source_id
        self.reason = reason
        super().__init__(f"Skill validation failed for '{source_id}': {reason}")


@dataclass(frozen=True)
class SkillResolutionWarning:
    """A non-fatal issue encountered while resolving a DIAL prompt skill."""

    url: str
    reason: str
