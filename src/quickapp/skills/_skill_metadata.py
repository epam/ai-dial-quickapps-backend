from typing import Any

from pydantic import BaseModel, Field


class SkillMetadata(BaseModel):
    """Metadata extracted from a skill file's YAML frontmatter."""

    name: str
    description: str
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, Any] | None = None
    allowed_tools: list[str] | None = None


class ParsedSkill(BaseModel):
    """Result of ``parse_frontmatter``: metadata plus non-fatal warnings."""

    metadata: SkillMetadata
    warnings: list[str] = Field(default_factory=list)
