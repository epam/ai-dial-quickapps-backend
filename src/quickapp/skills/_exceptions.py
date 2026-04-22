from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SkillValidationError(Exception):
    """Raised by ``parse_frontmatter`` when skill content is invalid."""

    def __init__(self, source_id: str, reason: str) -> None:
        self.source_id = source_id
        self.reason = reason
        super().__init__(f"Skill validation failed for '{source_id}': {reason}")


class SkillResolutionWarning(BaseModel):
    """A non-fatal issue encountered while resolving a DIAL prompt skill."""

    model_config = ConfigDict(frozen=True)

    url: str
    reason: str
